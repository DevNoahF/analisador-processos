"""Dashboard SHR local, autenticado e com jobs persistentes. Bind somente loopback."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.codex/scripts'))
from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from decidir_lote import decide_batch, load_tariffs
from extract_eproc import inventory
from supervisao import Limits, Supervisor, prepare
from providers import Provider
from app.workbooks import export_workbook, validate_xlsx

DATA = Path(os.environ.get('SHR_DATA_DIR', ROOT / 'data')).resolve()
DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
DATA.chmod(0o700)
LOCK = threading.RLock()
POOL = ThreadPoolExecutor(max_workers=1)
SESSIONS = {}
VAULT = {}
ATTEMPTS = {}
# IDs disponíveis precisam ser homologados e configurados pelo administrador.
MODELS = json.loads(os.environ.get('SHR_MODELS_JSON', '{"openai":[],"anthropic":[],"gemini":[]}'))
PUBLIC_HOST = os.environ.get('SHR_PUBLIC_HOST', '').strip().lower()
PUBLIC_URL = os.environ.get('SHR_PUBLIC_URL', '').strip().rstrip('/')
APP = FastAPI(title='SHR · Supervisão documental', docs_url=None, redoc_url=None, openapi_url=None)


@APP.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Não devolver entradas inválidas, que podem incluir senha/chave de API.
    return JSONResponse({'detail': 'Confira os campos, formatos e limites informados.'}, 422)


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


@APP.middleware('http')
async def protect(request, call_next):
    authority = request.headers.get('host', '').lower()
    host = authority.split(':')[0].strip('[]')
    allowed = {'127.0.0.1', 'localhost', 'testserver'}
    if PUBLIC_HOST:
        allowed.add(PUBLIC_HOST)
    if host not in allowed:
        return JSONResponse({'detail': 'Este servidor aceita apenas acesso local.'}, 403)
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        length = request.headers.get('content-length', '0')
        if not length.isdigit() or int(length) > 42_000_000:
            return JSONResponse({'detail': 'Solicitação excede o limite de tamanho.'}, 413)
        if request.headers.get('x-shr-client') != 'dashboard':
            return JSONResponse({'detail': 'Origem da solicitação não autorizada.'}, 403)
        origin = request.headers.get('origin')
        allowed_origins = {str(request.base_url).rstrip('/')}
        if PUBLIC_URL:
            allowed_origins.add(PUBLIC_URL)
        if origin and origin not in allowed_origins:
            return JSONResponse({'detail': 'Origem inválida.'}, 403)
    if request.url.path.startswith('/api/') and request.url.path not in {'/api/login', '/api/session'}:
        try:
            auth(request)
        except HTTPException:
            return JSONResponse({'detail': 'Entre para acessar seus documentos.'}, 401)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; frame-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response


def auth(request: Request):
    token = request.cookies.get('shr_session', '')
    with LOCK:
        session = SESSIONS.get(token)
        if not session or session['expires'] < time.time():
            SESSIONS.pop(token, None)
            raise HTTPException(401, 'Entre para acessar seus documentos.')
        return session['owner']


def job_path(job_id):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise HTTPException(404, 'Lote não encontrado.')
    return DATA / job_id


def get_job(job_id, owner):
    path = job_path(job_id) / 'job.json'
    if not path.exists():
        raise HTTPException(404, 'Lote não encontrado.')
    job = read(path)
    if job['owner'] != owner:
        raise HTTPException(404, 'Lote não encontrado.')
    return job


def put_job(job):
    save(job_path(job['id']) / 'job.json', job)


def idle(job):
    if job.get('busy'):
        raise HTTPException(409, 'Aguarde a etapa em andamento.')


def invalidate(job):
    job['revision'] += 1
    job['review'] = None
    job['export_revision'] = None
    job['status'] = 'ANALISE_INICIAL'


class Login(BaseModel):
    password: str = Field(min_length=10, max_length=200)


@APP.get('/api/session')
def session(request: Request):
    try:
        auth(request)
        signed = True
    except HTTPException:
        signed = False
    return {'initialized': (DATA / 'account.json').exists(), 'authenticated': signed,
            'shared_password_configured': bool(os.environ.get('SHR_SHARED_PASSWORD'))}


@APP.post('/api/login')
def login(body: Login, request: Request):
    with LOCK:
        now = time.time()
        ip = request.client.host
        attempts = [t for t in ATTEMPTS.get(ip, []) if t > now - 300]
        if len(attempts) >= 10:
            raise HTTPException(429, 'Muitas tentativas. Aguarde cinco minutos.')
        ATTEMPTS[ip] = attempts + [now]
        account_path = DATA / 'account.json'
        shared_password = os.environ.get('SHR_SHARED_PASSWORD')
        if shared_password and not hmac.compare_digest(body.password.encode(), shared_password.encode()):
            raise HTTPException(401, 'Senha de acesso incorreta.')
        if not account_path.exists():
            salt = secrets.token_hex(16)
            stored_password = shared_password or body.password
            digest = hashlib.scrypt(stored_password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
            save(account_path, {'salt': salt, 'hash': digest, 'owner': secrets.token_hex(16)})
        account = read(account_path)
        if shared_password:
            expected = hashlib.scrypt(shared_password.encode(), salt=bytes.fromhex(account['salt']), n=16384, r=8, p=1).hex()
            if not hmac.compare_digest(account['hash'], expected):
                # The administrator rotated the server secret; preserve the workspace ID.
                salt = secrets.token_hex(16)
                account.update(salt=salt, hash=hashlib.scrypt(shared_password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex())
                save(account_path, account)
        actual = hashlib.scrypt((shared_password or body.password).encode(), salt=bytes.fromhex(account['salt']), n=16384, r=8, p=1).hex()
        if not hmac.compare_digest(account['hash'], actual):
            raise HTTPException(401, 'Senha incorreta.')
        ATTEMPTS[ip] = []
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {'owner': account['owner'], 'expires': now + 8 * 3600}
        response = JSONResponse({'ok': True})
        response.set_cookie('shr_session', token, httponly=True, secure=PUBLIC_URL.startswith('https://'),
                            samesite='strict', max_age=8 * 3600)
        return response


@APP.post('/api/logout')
def logout(request: Request, owner=Depends(auth)):
    with LOCK:
        SESSIONS.pop(request.cookies.get('shr_session'), None)
        for key in list(VAULT):
            if VAULT[key]['owner'] == owner:
                del VAULT[key]
    response = JSONResponse({'ok': True})
    response.delete_cookie('shr_session')
    return response


@APP.get('/api/config')
def config(owner=Depends(auth)):
    return {'models': MODELS, 'tariffs': list(load_tariffs().values()), 'local_only': True,
            'limits': {'file_mb': 40, 'pdf_pages': 1500, 'batch_files': 30}}


@APP.get('/api/jobs')
def jobs(owner=Depends(auth)):
    with LOCK:
        result = [read(p) for p in DATA.glob('*/job.json')]
    return sorted([{'id': j['id'], 'name': j['name'], 'status': j['status'], 'created': j['created'],
                    'files': len(j['files']), 'records': len(j['records'])} for j in result if j['owner'] == owner],
                  key=lambda j: j['created'], reverse=True)


class NewJob(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    mode: str = 'new'


@APP.post('/api/jobs')
def create_job(body: NewJob, owner=Depends(auth)):
    if body.mode not in {'new', 'append'}:
        raise HTTPException(422, 'Modo inválido.')
    jid = secrets.token_hex(16)
    job_path(jid).mkdir(mode=0o700)
    job = {'id': jid, 'owner': owner, 'name': body.name, 'mode': body.mode, 'created': datetime.now(ZoneInfo('America/Sao_Paulo')).isoformat(),
           'status': 'RECEBIDO', 'files': [], 'records': [], 'review': None, 'busy': False,
           'revision': 0, 'export_revision': None, 'error': None}
    put_job(job)
    return job


@APP.get('/api/jobs/{jid}')
def show_job(jid: str, owner=Depends(auth)):
    with LOCK:
        job = get_job(jid, owner)
        documents = []
        for file in job['files']:
            inv = job_path(jid) / (file['id'] + '.json')
            if file['kind'] == 'pdf' and inv.exists():
                doc = read(inv)
                documents.append({'id': file['id'], 'name': file['name'], 'sha256': doc['sha256'],
                                  'pages': doc['page_count'], 'process': doc['primary_process'],
                                  'alerts': doc['alerts'], 'pending_pages': sum(bool(p.get('flags')) and not p.get('reading_verified') for p in doc['pages'])})
        job['documents'] = documents
        job['decisions'] = decide_batch(job['records'])['records'] if job['records'] else []
        return job


@APP.post('/api/jobs/{jid}/files')
def upload(jid: str, file: UploadFile = File(...), owner=Depends(auth)):
    with LOCK:
        job = get_job(jid, owner)
        idle(job)
        if len(job['files']) >= 31:
            raise HTTPException(400, 'Limite de 30 PDFs e uma planilha por lote.')
        fid = secrets.token_hex(16)
        path = job_path(jid) / fid
        size = 0
        try:
            with path.open('xb') as target:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 40_000_000:
                        raise ValueError('Arquivo maior que 40 MB.')
                    target.write(chunk)
            path.chmod(0o600)
            with path.open('rb') as source:
                magic = source.read(8)
            if magic.startswith(b'%PDF-'):
                import fitz
                with fitz.open(path) as pdf:
                    if pdf.needs_pass or not 0 < len(pdf) <= 1500:
                        raise ValueError('PDF protegido, vazio ou com mais de 1.500 páginas.')
                kind = 'pdf'
                if sum(f['kind'] == 'pdf' for f in job['files']) >= 30:
                    raise ValueError('Limite de 30 PDFs por lote.')
            elif magic.startswith(b'PK'):
                from plan_workbook import read_existing
                validate_xlsx(path)
                read_existing(path)
                if job['mode'] != 'append' or any(f['kind'] == 'xlsx' for f in job['files']):
                    raise ValueError('Planilha permitida apenas uma vez no modo acrescentar.')
                kind = 'xlsx'
            else:
                raise ValueError('Envie um PDF ou XLSX válido.')
        except Exception as exc:
            path.unlink(missing_ok=True)
            message = str(exc) if isinstance(exc, ValueError) else 'Não foi possível ler este arquivo.'
            raise HTTPException(400, message) from None
        name = Path(file.filename or 'documento').name[:160]
        job['files'].append({'id': fid, 'name': name, 'kind': kind, 'bytes': size})
        invalidate(job)
        job['status'] = 'RECEBIDO'
        put_job(job)
        return {'id': fid, 'name': name, 'kind': kind}


def extract_worker(jid, owner):
    try:
        with LOCK:
            job = get_job(jid, owner)
        for file in job['files']:
            if file['kind'] != 'pdf':
                continue
            destination = job_path(jid) / (file['id'] + '.json')
            if not destination.exists():
                doc = inventory(job_path(jid) / file['id'])
                doc['file_name'] = file['name']
                save(destination, doc)
        with LOCK:
            job = get_job(jid, owner)
            docs = inventories(job)
            # Capa gera triagem, nunca prova de ato remunerável.
            known = {s for r in job['records'] for s in r.get('source_ids', [])}
            for doc in docs:
                if doc['sha256'] in known:
                    continue
                known.add(doc['sha256'])
                uf = next((d['uf'] for d in doc['documents'] if d['process'] == doc['primary_process']), '')
                job['records'].append({'record_id': secrets.token_hex(12), 'source_ids': [doc['sha256']],
                    'process': doc['primary_process'] or '', 'uf': uf, 'shr_activity': 'PENDENTE',
                    'billing_history': 'PENDENTE', 'evidence': [],
                    'observation': 'Triagem da capa. Conferir identidade, atos e fontes; não representa ato remunerável confirmado.'})
            job['status'] = 'ANALISE_INICIAL'
            job['error'] = None
            invalidate(job)
            job['busy'] = False
            put_job(job)
    except Exception:
        fail_job(jid, owner, 'Falha na extração. Confira se o PDF está íntegro e tente novamente.')


def fail_job(jid, owner, message):
    with LOCK:
        job = get_job(jid, owner)
        job.update(status='PENDENTE', busy=False, error=message)
        VAULT.pop(jid, None)
        put_job(job)


def inventories(job):
    return [read(job_path(job['id']) / (f['id'] + '.json')) for f in job['files']
            if f['kind'] == 'pdf' and (job_path(job['id']) / (f['id'] + '.json')).exists()]


@APP.post('/api/jobs/{jid}/extract')
def extract(jid: str, owner=Depends(auth)):
    with LOCK:
        job = get_job(jid, owner)
        idle(job)
        if not any(f['kind'] == 'pdf' for f in job['files']):
            raise HTTPException(400, 'Adicione pelo menos um PDF.')
        job.update(status='EXTRAINDO', busy=True, error=None)
        put_job(job)
        POOL.submit(extract_worker, jid, owner)
    return {'status': 'EXTRAINDO'}


def get_doc(jid, fid, owner):
    job = get_job(jid, owner)
    if not any(f['id'] == fid and f['kind'] == 'pdf' for f in job['files']):
        raise HTTPException(404, 'Documento não encontrado.')
    path = job_path(jid) / (fid + '.json')
    if not path.exists():
        raise HTTPException(409, 'Extraia os PDFs primeiro.')
    return job, read(path)


@APP.get('/api/jobs/{jid}/pages/{fid}/{page}')
def page_data(jid: str, fid: str, page: int, owner=Depends(auth)):
    _, doc = get_doc(jid, fid, owner)
    if not 1 <= page <= len(doc['pages']):
        raise HTTPException(404, 'Página não encontrada.')
    return doc['pages'][page - 1]


@APP.get('/api/jobs/{jid}/images/{fid}/{page}')
def page_image(jid: str, fid: str, page: int, owner=Depends(auth)):
    _, doc = get_doc(jid, fid, owner)
    if not 1 <= page <= len(doc['pages']):
        raise HTTPException(404, 'Página não encontrada.')
    import fitz
    with fitz.open(job_path(jid) / fid) as pdf:
        p = pdf[page - 1]
        scale = min(1.5, 1800 / max(p.rect.width, p.rect.height))
        return Response(p.get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes('png'), media_type='image/png')


class Reading(BaseModel):
    text: str = Field(max_length=150000)
    source: str = Field(min_length=10, max_length=1000)


@APP.post('/api/jobs/{jid}/pages/{fid}/{page}')
def verify_page(jid: str, fid: str, page: int, body: Reading, owner=Depends(auth)):
    with LOCK:
        job, doc = get_doc(jid, fid, owner)
        idle(job)
        if not 1 <= page <= len(doc['pages']) or not body.text.strip():
            raise HTTPException(400, 'Informe texto completo ou marcador de página comprovadamente em branco.')
        doc['pages'][page - 1].update(text=body.text, reading_verified=True, reading_source=body.source)
        save(job_path(jid) / (fid + '.json'), doc)
        invalidate(job)
        put_job(job)
    return {'ok': True}


class Records(BaseModel):
    records: list[dict] = Field(max_length=1000)


@APP.put('/api/jobs/{jid}/records')
def update_records(jid: str, body: Records, owner=Depends(auth)):
    with LOCK:
        job = get_job(jid, owner)
        idle(job)
        if len(json.dumps(body.records)) > 2_000_000:
            raise HTTPException(400, 'Registros muito grandes.')
        try:
            prepare(inventories(job), body.records)
            if body.records:
                decide_batch(body.records)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(400, 'Registros inválidos. Preserve IDs únicos, fontes do lote e os tipos dos campos.') from None
        job['records'] = body.records
        invalidate(job)
        put_job(job)
    return {'ok': True}


class ReviewConfig(BaseModel):
    provider: str
    model: str
    max_calls: int = Field(default=200, ge=1, le=1000)
    max_input_estimate: int = Field(default=1500000, ge=1000, le=50000000)
    max_output_total: int = Field(default=160000, ge=1600, le=2000000)


def plan_for(job, body):
    limits = Limits(max_calls=body.max_calls, max_input_estimate=body.max_input_estimate, max_output_total=body.max_output_total)
    try:
        if len(inventories(job)) != sum(f['kind'] == 'pdf' for f in job['files']):
            raise ValueError('Extração incompleta')
        plan = prepare(inventories(job), job['records'], limits)
    except (ValueError, TypeError, KeyError):
        raise HTTPException(400, 'Extraia os documentos e confira os registros antes da revisão.') from None
    return limits, plan


@APP.post('/api/jobs/{jid}/preflight')
def preflight(jid: str, body: ReviewConfig, owner=Depends(auth)):
    job = get_job(jid, owner)
    _, plan = plan_for(job, body)
    return plan['preflight']


class StartReview(ReviewConfig):
    api_key: str = Field(min_length=10, max_length=500)


def review_worker(jid, owner, body):
    try:
        with LOCK:
            job = get_job(jid, owner)
            secret = VAULT.get(jid)
            if not secret or secret['owner'] != owner or secret['expires'] < time.time():
                raise ValueError('Credencial expirada')
            key = secret['key']
        limits, plan = plan_for(job, body)
        runner = Supervisor(owner_id=owner, job_id=jid, provider=Provider(body.provider, body.model),
                            limits=limits, checkpoint=job_path(jid) / 'review.checkpoint.json')
        result = runner.run(plan, api_key=key)
        with LOCK:
            job = get_job(jid, owner)
            job.update(review=result, busy=False, status='PRONTO_PARA_EXPORTAR' if result['status'] == 'REVISAO_CONCLUIDA' else 'PENDENTE')
            put_job(job)
    except Exception:
        fail_job(jid, owner, 'Revisão interrompida. Verifique configuração, orçamento e checkpoint. Nenhuma aprovação financeira foi realizada.')
    finally:
        with LOCK:
            VAULT.pop(jid, None)


@APP.post('/api/jobs/{jid}/review')
def start_review(jid: str, body: StartReview, owner=Depends(auth)):
    with LOCK:
        job = get_job(jid, owner)
        idle(job)
        if body.provider not in MODELS or body.model not in MODELS[body.provider]:
            raise HTTPException(400, 'Modelo não homologado no catálogo do servidor.')
        plan_for(job, body)
        previous = job.get('provider')
        if previous and (previous != body.provider or job.get('model') != body.model):
            raise HTTPException(409, 'Use um novo lote para mudar provedor ou modelo.')
        VAULT[jid] = {'owner': owner, 'key': body.api_key, 'expires': time.time() + 3600}
        # Enfileirar apenas configuração; a chave permanece no cofre de memória.
        clean = ReviewConfig(**body.model_dump(exclude={'api_key'}))
        job.update(provider=body.provider, model=body.model, status='REVISAO_PAGINAS', busy=True, error=None)
        put_job(job)
        POOL.submit(review_worker, jid, owner, clean)
    return {'status': 'REVISAO_PAGINAS'}


def local_review(job):
    from supervisao import digest, rule_snapshot
    docs = inventories(job)
    decisions = decide_batch(job['records'])['records'] if job['records'] else []
    rows = []
    for raw, decision in zip(job['records'], decisions):
        decision.update(record_id=raw['record_id'], source_ids=raw['source_ids'],
                        supervision={'status': 'REVISAO_API_NAO_EXECUTADA'})
        if decision['status'] != 'JÁ FATURADO':
            decision['status'] = 'PENDENTE'
        decision['pending'].append('Revisão por API não executada; análise preliminar local.')
        rows.append(decision)
    return {'job_id': job['id'], 'provider': 'local', 'model': 'não utilizado', 'rules_hash': digest(rule_snapshot()),
            'records': rows, 'coverage': [{'file_name': d['file_name'], 'page_count': d['page_count'],
                'text_review_complete': False, 'reading_complete': False,
                'reading_pending': [{'page': p['pdf_page'], 'flags': p['flags']} for p in d['pages'] if not p.get('reading_verified')]} for d in docs],
            'usage': {}, 'status': 'PENDENTE'}


@APP.post('/api/jobs/{jid}/export')
def export(jid: str, owner=Depends(auth)):
    with LOCK:
        job = get_job(jid, owner)
        idle(job)
        if not inventories(job):
            raise HTTPException(400, 'Extraia os documentos antes de exportar.')
        if job['export_revision'] == job['revision']:
            return {'url': f'/api/jobs/{jid}/download', 'report_url': f'/api/jobs/{jid}/report'}
        existing = next((job_path(jid) / f['id'] for f in job['files'] if f['kind'] == 'xlsx'), None)
        if job['mode'] == 'append' and existing is None:
            raise HTTPException(400, 'Envie a planilha original para acrescentar os lançamentos.')
        try:
            review = job['review'] or local_review(job)
            data, plan = export_workbook(job['records'], review, mode=job['mode'], existing=existing)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from None
        output = job_path(jid) / 'resultado.tmp'
        output.write_bytes(data)
        output.chmod(0o600)
        output.replace(job_path(jid) / 'resultado.xlsx')
        save(job_path(jid) / 'relatorio.json', {'review': review, 'conflicts': plan['conflicts'], 'new_rows': len(plan['append'])})
        job.update(export_revision=job['revision'], status='EXPORTADO')
        put_job(job)
        return {'url': f'/api/jobs/{jid}/download', 'report_url': f'/api/jobs/{jid}/report', 'rows': len(plan['append']), 'conflicts': len(plan['conflicts'])}


@APP.get('/api/jobs/{jid}/download')
def download(jid: str, owner=Depends(auth)):
    job = get_job(jid, owner)
    if job['export_revision'] != job['revision'] or job['export_revision'] is None:
        raise HTTPException(409, 'Exporte a versão atual primeiro.')
    return FileResponse(job_path(jid) / 'resultado.xlsx', filename='FORCA_TAREFA_SHR.xlsx')


@APP.get('/api/jobs/{jid}/report')
def report(jid: str, owner=Depends(auth)):
    job = get_job(jid, owner)
    if job['export_revision'] != job['revision'] or job['export_revision'] is None:
        raise HTTPException(409, 'Exporte a versão atual primeiro.')
    return FileResponse(job_path(jid) / 'relatorio.json', filename='relatorio_SHR.json')


# Reinício não reenvia chamadas em estado indeterminado nem restaura credenciais.
for path in DATA.glob('*/job.json'):
    job = read(path)
    if job.get('busy'):
        job.update(busy=False, status='PENDENTE', error='Servidor reiniciado. Confira o checkpoint antes de retomar; reinsira a chave no site.')
        save(path, job)
APP.mount('/', StaticFiles(directory=ROOT / 'app/static', html=True), name='static')
