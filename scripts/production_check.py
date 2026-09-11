#!/usr/bin/env python3
from __future__ import annotations
import argparse, asyncio, os, re, sys
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from cryptography.fernet import Fernet
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=ROOT.parents[1]

def env_values():
    vals={k:str(v or '') for k,v in dotenv_values(ROOT/'backend'/'.env').items()}
    for k,v in os.environ.items():
        if k in {'DATABASE_URL','DB_URL','APP_PASSWORD','TG_API_ID','TG_API_HASH','SECRETS_ENCRYPTION_KEY','COOKIE_SECURE','TRUST_PROXY_HEADERS','ALLOWED_ORIGIN','ENFORCE_SINGLE_INSTANCE'}:
            vals[k]=v
    return vals

def truthy(v): return str(v or '').strip().lower() in {'1','true','yes','on'}

def normalize_async_url(raw: str) -> str:
    if raw.startswith('postgres://'):
        return 'postgresql+asyncpg://' + raw[len('postgres://'):]
    if raw.startswith('postgresql://'):
        return 'postgresql+asyncpg://' + raw[len('postgresql://'):]
    return raw

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
    if is_postgres: ok.append('Đã cấu hình PostgreSQL bền vững')
    else: blockers.append('Chưa cấu hình DATABASE_URL PostgreSQL bền vững; SQLite không phù hợp làm lưu trữ production trên Replit')
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
    pw=v.get('APP_PASSWORD','')
    if len(pw)>=12 and 'change-me' not in pw: ok.append('Đã cấu hình APP_PASSWORD')
    else: blockers.append('APP_PASSWORD phải được cấu hình bằng giá trị mạnh (từ 12 ký tự)')
    if str(v.get('TG_API_ID','')).strip() not in {'','0'} and v.get('TG_API_HASH','').strip(): ok.append('Đã cấu hình thông tin Telegram API')
    else: blockers.append('Chưa cấu hình TG_API_ID/TG_API_HASH')
    key=v.get('SECRETS_ENCRYPTION_KEY','').strip()
    try:
        Fernet(key.encode('ascii')); ok.append('SECRETS_ENCRYPTION_KEY là Fernet key hợp lệ')
    except Exception: blockers.append('Thiếu SECRETS_ENCRYPTION_KEY hoặc key không hợp lệ')
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
