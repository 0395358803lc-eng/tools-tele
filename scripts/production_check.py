#!/usr/bin/env python3
from __future__ import annotations
import argparse, asyncio, os, re, sys
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from cryptography.fernet import Fernet
from dotenv import dotenv_values

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=ROOT.parents[1]
if str(ROOT / 'backend') not in sys.path:
    sys.path.insert(0, str(ROOT / 'backend'))

def env_values():
    vals={k:str(v or '') for k,v in dotenv_values(ROOT/'backend'/'.env').items()}
    for k,v in os.environ.items():
        if k in {'DATABASE_URL','DB_URL','SUPABASE_URL','SUPABASE_PUBLISHABLE_KEY','SUPABASE_SECRET_KEY','SUPABASE_JWKS_URL','TG_API_ID','TG_API_HASH','SESSIONS_DIR','COOKIE_SECURE','TRUST_PROXY_HEADERS','ALLOWED_ORIGIN','ENFORCE_SINGLE_INSTANCE','NODE_ENV'}:
            vals[k]=v
    return vals

def truthy(v): return str(v or '').strip().lower() in {'1','true','yes','on'}

def normalize_async_url(raw: str) -> str:
    raw = raw.replace('?sslmode=', '?ssl=').replace('&sslmode=', '&ssl=')
    if raw.startswith('postgres://'):
        return 'postgresql+asyncpg://' + raw[len('postgres://'):]
    if raw.startswith('postgresql://'):
        return 'postgresql+asyncpg://' + raw[len('postgresql://'):]
    if raw.startswith('sqlite+aiosqlite:///'):
        tail = raw[len('sqlite+aiosqlite:///'):]
        if tail and not tail.startswith('/'):
            return 'sqlite+aiosqlite:///' + str((ROOT / 'backend' / tail).resolve())
    return raw

async def database_has_telegram_api(raw_url: str, encryption_key: str) -> bool:
    if not raw_url or not encryption_key:
        return False
    try:
        cipher = Fernet(encryption_key.encode('ascii'))
    except Exception:
        return False
    engine=create_async_engine(normalize_async_url(raw_url), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            rows=(await conn.execute(text("select key, ciphertext from encrypted_secrets where key in ('telegram:api_id','telegram:api_hash')"))).all()
        values={}
        for name, token in rows:
            try:
                values[str(name)] = cipher.decrypt(str(token).encode('ascii')).decode('utf-8').strip()
            except Exception:
                return False
        api_id=values.get('telegram:api_id','')
        api_hash=values.get('telegram:api_hash','')
        return api_id.isdigit() and int(api_id) > 0 and bool(api_hash)
    except Exception:
        return False
    finally:
        await engine.dispose()

def expected_head() -> str | None:
    cfg=Config(str(ROOT/'backend'/'alembic.ini'))
    return ScriptDirectory.from_config(cfg).get_current_head()

async def database_revision(raw_url: str) -> str | None:
    engine=create_async_engine(normalize_async_url(raw_url), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            return await conn.scalar(text('select version_num from alembic_version'))
    finally:
        await engine.dispose()

def main():
    ap=argparse.ArgumentParser(description='Kiểm tra điều kiện cần thiết để chạy Multi TG Manager ở production')
    ap.add_argument('--strict',action='store_true',help='Thoát với mã khác 0 khi còn điều kiện chặn')
    ap.add_argument('--check-db',action='store_true',help='Đồng thời kết nối PostgreSQL và yêu cầu đúng Alembic head hiện tại')
    args=ap.parse_args()
    v=env_values(); blockers=[]; warnings=[]; ok=[]
    db=(v.get('DATABASE_URL') or v.get('DB_URL') or '').strip()
    is_postgres=db.startswith(('postgres://','postgresql://','postgresql+asyncpg://'))
    if is_postgres:
        ok.append('Đã cấu hình PostgreSQL bền vững')
        try:
            parsed = make_url(normalize_async_url(db))
            if (parsed.host or '').lower().endswith('.pooler.supabase.com') and parsed.port == 6543:
                blockers.append('Supabase Transaction pooler port 6543 không phù hợp vì ứng dụng cần session-level advisory lock; hãy dùng Session pooler port 5432')
        except Exception:
            blockers.append('DATABASE_URL PostgreSQL không hợp lệ')
    else:
        blockers.append('Chưa cấu hình DATABASE_URL PostgreSQL bền vững; SQLite không phù hợp làm lưu trữ production')
    if args.check_db and is_postgres:
        try:
            revision=asyncio.run(database_revision(db))
            head=expected_head()
            if revision and head and revision == head:
                ok.append(f'Kết nối PostgreSQL thành công tại Alembic head {head}')
            else:
                blockers.append(f'Phiên bản schema PostgreSQL không khớp: hiện tại={revision or "thiếu"}, yêu cầu={head or "không rõ"}')
        except Exception as exc:
            blockers.append(f'Kiểm tra kết nối/schema PostgreSQL thất bại ({type(exc).__name__})')
    supabase_required = ['SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY', 'SUPABASE_SECRET_KEY']
    missing_supabase = [k for k in supabase_required if not v.get(k, '').strip()]
    if not missing_supabase:
        ok.append('Đã cấu hình Supabase Identity')
    else:
        blockers.append('Thiếu cấu hình Supabase Identity: ' + ', '.join(missing_supabase))
    sessions_dir=Path(v.get('SESSIONS_DIR') or './sessions')
    if not sessions_dir.is_absolute(): sessions_dir=(ROOT/'backend'/sessions_dir).resolve()
    key_file=sessions_dir/'.encryption.key'
    key=''; key_valid=False
    if key_file.is_file():
        try:
            key=key_file.read_text(encoding='ascii').strip(); Fernet(key.encode('ascii')); key_valid=True
            ok.append('Khóa mã hóa nội bộ hợp lệ')
        except Exception: blockers.append('Khóa mã hóa nội bộ bị hỏng hoặc không hợp lệ')
    else:
        key_valid=True; ok.append('Khóa mã hóa nội bộ sẽ được tạo tự động khi ứng dụng chạy')
    ok.append('Telegram API được cấu hình riêng cho từng user sau đăng nhập')
    if truthy(v.get('COOKIE_SECURE')):
        ok.append('Đã bật cookie bảo mật')
    elif args.strict:
        blockers.append('Production HTTPS yêu cầu COOKIE_SECURE=true')
    else:
        warnings.append('Hãy đặt COOKIE_SECURE=true khi chạy production qua HTTPS')
    singleton_enabled = truthy(v.get('ENFORCE_SINGLE_INSTANCE', 'true'))
    if singleton_enabled:
        ok.append('Đã bật cơ chế PostgreSQL bảo vệ chế độ một instance')
    elif args.strict:
        blockers.append('Telegram production yêu cầu ENFORCE_SINGLE_INSTANCE=true')
    else:
        warnings.append('Hãy bật ENFORCE_SINGLE_INSTANCE trước khi chạy production')

    configured_origins = [x.strip().lower() for x in v.get('ALLOWED_ORIGIN', '').split(',') if x.strip()]
    local_origins = [x for x in configured_origins if '://localhost' in x or '://127.0.0.1' in x]
    if local_origins and args.strict:
        blockers.append('Không được dùng ALLOWED_ORIGIN chỉ dành cho dev trong production: ' + ', '.join(local_origins))
    elif local_origins:
        warnings.append('Hãy xóa localhost/127.0.0.1 khỏi ALLOWED_ORIGIN trước khi chạy production')

    if truthy(v.get('TRUST_PROXY_HEADERS')): ok.append('Đã bật header của reverse proxy đáng tin cậy')
    else: warnings.append('Chỉ đặt TRUST_PROXY_HEADERS=true khi deploy phía sau Replit/reverse proxy HTTPS đáng tin cậy')
    repl=WORKSPACE/'.replit'
    target='unknown'
    if repl.exists():
        m=re.search(r'deploymentTarget\s*=\s*"([^"]+)"',repl.read_text(encoding='utf-8'))
        if m: target=m.group(1)
    if target=='autoscale':
        msg='Deployment hiện là autoscale; hãy dùng Reserved VM/kiểu luôn hoạt động cho listener/kết nối Telegram dài hạn'
        if args.strict: blockers.append(msg)
        else: warnings.append(msg)
    else: ok.append(f'Kiểu deployment: {target}')
    print('KIỂM TRA PRODUCTION')
    for x in ok: print('  ĐẠT     ',x)
    for x in warnings: print('  CẢNH BÁO ',x)
    for x in blockers: print('  CHẶN    ',x)
    print(f'TỔNG KẾT chặn={len(blockers)} cảnh_báo={len(warnings)} đạt={len(ok)}')
    if args.strict and blockers: raise SystemExit(1)

if __name__=='__main__': main()
