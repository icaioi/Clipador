"""Signed, staged GitHub updates. User documents are never installation inputs."""
from pathlib import Path,PurePosixPath
import base64,hashlib,json,os,re,shutil,tempfile,urllib.parse,urllib.request,zipfile
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

class UpdateError(Exception):pass
class UpdateCancelled(Exception):pass
class InstallationInvalid(UpdateError):pass

_ROOT_FILES={'Clipador.exe','ClipadorWorker.exe','ClipadorLauncher.exe','ffmpeg.exe','ffprobe.exe'}
_SHA=re.compile(r'[0-9a-f]{64}\Z')

def _relative(name):
    if not isinstance(name,str) or not name or any(char in name for char in '\\:\0<>"|?*'):
        raise UpdateError('Caminho inválido na atualização.')
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or str(path)!=name:
        raise UpdateError('Caminho fora da instalação.')
    if any(part.endswith((' ','.')) for part in path.parts):
        raise UpdateError('Nome de arquivo inválido para Windows.')
    if any(re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])',part.split('.',1)[0],re.I) for part in path.parts):
        raise UpdateError('Nome reservado do Windows na atualização.')
    if name not in _ROOT_FILES and (len(path.parts)<2 or path.parts[0]!='_internal'):
        raise UpdateError('A atualização tentou alterar dados fora do programa.')
    return Path(*path.parts)

def _digest(file):
    with Path(file).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def _valid(file,record):
    try:return file.is_file() and file.stat().st_size==record['size'] and _digest(file)==record['sha256']
    except OSError:return False

def _https(url):
    if urllib.parse.urlsplit(url).scheme!='https':raise UpdateError('Atualizações exigem HTTPS.')

class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        _https(newurl)
        return super().redirect_request(request,fp,code,msg,headers,newurl)

class Updater:
    def __init__(self,config,store,notify=None,cancel=None,transport=None):
        self.repository=config['repository']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',self.repository):raise UpdateError('Repositório inválido.')
        self.public_key=Ed25519PublicKey.from_public_bytes(base64.b64decode(config['public_key'],validate=True))
        self.runtime=config['runtime']
        self.store=Path(store)
        self.notify=notify or (lambda message,progress:None)
        self.cancel=cancel or (lambda:False)
        self.transport=transport or urllib.request.build_opener(_Redirects()).open

    def _check_cancel(self):
        if self.cancel():raise UpdateCancelled()

    def _open(self,url):
        self._check_cancel();_https(url)
        request=urllib.request.Request(url,headers={'User-Agent':'Clipador-Updater/1','Accept':'application/vnd.github+json'})
        return self.transport(request,timeout=15)

    def _small(self,url):
        with self._open(url) as stream:data=stream.read(4*1024*1024+1)
        if len(data)>4*1024*1024:raise UpdateError('Metadados da versão excederam o limite.')
        return data

    def verify(self,payload,signature):
        try:
            self.public_key.verify(base64.b64decode(signature.strip(),validate=True),payload)
        except (ValueError,InvalidSignature) as error:
            raise UpdateError('Assinatura da atualização inválida; nenhum arquivo foi instalado.') from error
        try:manifest=json.loads(payload)
        except (ValueError,UnicodeError) as error:raise UpdateError('Manifesto de atualização inválido.') from error
        if not isinstance(manifest,dict) or type(manifest.get('schema')) is not int or manifest['schema']!=1 or type(manifest.get('generation')) is not int or manifest['generation']<1:
            raise UpdateError('Versão de atualização inválida.')
        version=manifest.get('version');commit=manifest.get('commit')
        if not isinstance(version,str) or not re.fullmatch(r'v1\.0\.[0-9]+',version) or not isinstance(commit,str) or not re.fullmatch(r'[0-9a-f]{40}',commit):
            raise UpdateError('Identidade da versão inválida.')
        if not isinstance(manifest.get('runtime'),str) or not manifest['runtime']:
            raise UpdateError('Runtime da versão inválido.')
        records=manifest.get('files')
        if not isinstance(records,list) or not 1<=len(records)<=20000:raise UpdateError('Lista de arquivos inválida.')
        names=set();folded=set()
        for record in records:
            if not isinstance(record,dict):raise UpdateError('Registro de arquivo inválido.')
            name=record.get('path');_relative(name)
            if name.casefold() in folded:raise UpdateError('Arquivos duplicados na atualização.')
            if type(record.get('size')) is not int or record['size']<0 or not isinstance(record.get('sha256'),str) or not _SHA.fullmatch(record['sha256']):
                raise UpdateError('Integridade de arquivo inválida.')
            names.add(name);folded.add(name.casefold())
        if not {'Clipador.exe','ClipadorWorker.exe','ClipadorLauncher.exe','_internal/version.json'}<=names:
            raise UpdateError('Versão sem os executáveis obrigatórios.')
        updates=manifest.get('update_files')
        if not isinstance(updates,list) or not all(isinstance(name,str) for name in updates) or len(updates)!=len(set(updates)) or not set(updates)<=names:
            raise UpdateError('Lista do pacote incremental inválida.')
        for kind,expected in (('update','Clipador-update.zip'),('full','Clipador-full.zip')):
            info=manifest.get(kind,{})
            if not isinstance(info,dict) or info.get('name')!=expected or type(info.get('size')) is not int or not 0<info['size']<=2*1024**3 or not isinstance(info.get('sha256'),str) or not _SHA.fullmatch(info['sha256']):
                raise UpdateError('Pacote de atualização inválido.')
        return manifest

    def _destination(self,manifest):
        return self.store/'versions'/(str(manifest['generation'])+'-'+manifest['commit'][:12])

    def _inventory_valid(self,folder,records):
        for record in records:
            self._check_cancel()
            if not _valid(folder/_relative(record['path']),record):return False
        return True

    def current(self):
        pointer=self.store/'current.json'
        if not pointer.is_file():return None
        try:
            record=json.loads(pointer.read_text(encoding='utf-8'))
            if not isinstance(record,dict):return None
            payload=base64.b64decode(record['manifest'],validate=True)
            signature=record['signature'].encode('ascii')
            manifest=self.verify(payload,signature)
            folder=self._destination(manifest)
            self.notify('Verificando integridade da versão instalada...',.01)
            if not self._inventory_valid(folder,manifest['files']):return None
            return folder
        except (OSError,ValueError,KeyError,TypeError,UpdateError):return None

    def _asset_url(self,version,name):
        return 'https://github.com/'+self.repository+'/releases/download/'+urllib.parse.quote(version,safe='')+'/'+name

    def _download(self,manifest,kind,target):
        info=manifest[kind];size=0;sha=hashlib.sha256();last=-1
        with self._open(self._asset_url(manifest['version'],info['name'])) as stream,target.open('wb') as file:
            while chunk:=stream.read(1024*1024):
                self._check_cancel();size+=len(chunk)
                if size>info['size']:raise UpdateError('Download maior que o pacote assinado.')
                file.write(chunk);sha.update(chunk)
                percent=size*100//info['size']
                if percent!=last:
                    last=percent;self.notify('Baixando atualização: '+str(percent)+'%',.1+.55*size/info['size'])
        if size!=info['size'] or sha.hexdigest()!=info['sha256']:
            raise UpdateError('O pacote recebido não corresponde à versão assinada.')

    def _extract(self,archive,stage,records,prefix=''):
        expected={record['path']:record for record in records}
        with zipfile.ZipFile(archive) as source:
            infos=source.infolist()
            if len(infos)!=len(expected):raise UpdateError('Conteúdo do ZIP difere do manifesto.')
            seen=set()
            for info in infos:
                self._check_cancel()
                if not info.filename.startswith(prefix):raise UpdateError('Pasta inesperada no ZIP.')
                name=info.filename[len(prefix):];relative=_relative(name)
                if name in seen or name not in expected or info.is_dir() or (info.external_attr>>16)&0o170000==0o120000:
                    raise UpdateError('Arquivo inesperado ou link no ZIP.')
                record=expected[name]
                if info.file_size!=record['size']:raise UpdateError('Tamanho incorreto dentro do ZIP.')
                destination=stage/relative
                destination.parent.mkdir(parents=True,exist_ok=True)
                sha=hashlib.sha256();count=0
                with source.open(info) as stream,destination.open('xb') as output:
                    while chunk:=stream.read(1024*1024):
                        self._check_cancel();count+=len(chunk)
                        if count>record['size']:raise UpdateError('Arquivo descompactado excedeu o limite.')
                        output.write(chunk);sha.update(chunk)
                if count!=record['size'] or sha.hexdigest()!=record['sha256']:raise UpdateError('Arquivo da atualização foi corrompido.')
                seen.add(name)

    def _reuse(self,current,stage,records):
        for record in records:
            self._check_cancel()
            relative=_relative(record['path']);source=current/relative
            if not _valid(source,record):return False
            destination=stage/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            try:os.link(source,destination)
            except OSError:shutil.copy2(source,destination)
        return True

    def prepare(self,current):
        current=Path(current)
        self.notify('Consultando nova versão...',.02)
        latest=json.loads(self._small('https://api.github.com/repos/'+self.repository+'/releases/latest'))
        version=latest.get('tag_name','')
        if not re.fullmatch(r'v1\.0\.[0-9]+',version):raise UpdateError('Publicação sem versão válida.')
        payload=self._small(self._asset_url(version,'release.json'))
        signature=self._small(self._asset_url(version,'release.sig'))
        manifest=self.verify(payload,signature)
        if manifest['version']!=version:raise UpdateError('Manifesto não pertence à publicação atual.')
        try:installed=json.loads((current/'_internal'/'version.json').read_text(encoding='utf-8')).get('generation',0)
        except (OSError,ValueError):installed=0
        self._check_cancel()
        if manifest['generation']<installed:return current
        if manifest['generation']==installed:
            if not self._inventory_valid(current,manifest['files']):
                raise InstallationInvalid('Arquivos locais foram alterados ou corrompidos. Abra o launcher original ou extraia o pacote novamente.')
            return current
        self.store.mkdir(parents=True,exist_ok=True)
        versions=self.store/'versions';versions.mkdir(exist_ok=True)
        destination=self._destination(manifest)
        with tempfile.TemporaryDirectory(prefix='.download-',dir=self.store) as cache:
            stage=Path(tempfile.mkdtemp(prefix='.staging-',dir=versions))
            try:
                update_names=set(manifest['update_files'])
                unchanged=[record for record in manifest['files'] if record['path'] not in update_names]
                incremental=manifest['runtime']==self.runtime and self._reuse(current,stage,unchanged)
                archive=Path(cache)/'payload.zip'
                if incremental:
                    self._download(manifest,'update',archive)
                    self._extract(archive,stage,[record for record in manifest['files'] if record['path'] in update_names])
                else:
                    shutil.rmtree(stage);stage.mkdir()
                    self._download(manifest,'full',archive)
                    self._extract(archive,stage,manifest['files'],'Clipador/')
                self._check_cancel();self.notify('Ativando a nova versão...',.95)
                receipt={'manifest':base64.b64encode(payload).decode('ascii'),'signature':signature.decode('ascii').strip()}
                (stage/'.release-receipt.json').write_text(json.dumps(receipt),encoding='utf-8')
                if destination.exists():
                    if self._inventory_valid(destination,manifest['files']):
                        (destination/'.release-receipt.json').write_text(json.dumps(receipt),encoding='utf-8')
                        shutil.rmtree(stage)
                    else:
                        if destination==current:raise InstallationInvalid('A versão em execução precisa ser reparada pelo launcher original.')
                        shutil.rmtree(destination);stage.rename(destination)
                else:stage.rename(destination)
                self._check_cancel()
                pointer=self.store/'current.tmp'
                pointer.write_text(json.dumps(receipt),encoding='utf-8');pointer.replace(self.store/'current.json')
                self._prune({destination,current})
                self.notify('Atualização concluída.',1)
                return destination
            finally:
                if stage.exists():shutil.rmtree(stage)

    def _prune(self,keep):
        for folder in (self.store/'versions').iterdir():
            if folder in keep or not re.fullmatch(r'[0-9]+-[0-9a-f]{12}',folder.name):continue
            try:shutil.rmtree(folder)
            except OSError:pass  # A running older version retains its files until a later launch.
