import base64
import pytest
from aiohttp.test_utils import TestClient, TestServer
from prollama.daemon import make_app
from prollama.supervisor import Supervisor

@pytest.mark.asyncio
async def test_dashboard_rejects_unauthorized_access(tmp_path):
    password=tmp_path/'password'; password.write_text('a-long-test-password\n')
    fake=tmp_path/'fake-executable'; fake.write_text('#!/bin/sh\n'); fake.chmod(0o755)
    cfg={"binary":str(fake), "state_dir":str(tmp_path/'state'), "admin_password_file":str(password),
         "admin_username":"admin", "profiles":{"cpu":{"description":"CPU","env":{},"gpu_ids":[]}},
         "public_ports":{"ranges":[[8080,8090]],"sets":[]},
         "backend_ports":{"ranges":[[18080,18090]],"sets":[]},
         "admin_port":18765,"nginx_apply_command":[]}
    app=make_app(cfg, Supervisor(cfg))
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            r=await client.get('/api/state')
            assert r.status==401
            header='Basic '+base64.b64encode(b'admin:a-long-test-password').decode()
            r=await client.get('/api/state',headers={'Authorization':header})
            assert r.status==200
            r=await client.post('/api/models/scan',json={}, headers={'Authorization':header})
            assert r.status==403
            r=await client.post('/api/models/scan',json={},headers={'Authorization':header,'X-Prollama-Request':'1',
                         'Origin':'https://evil.example'})
            assert r.status==403
            r=await client.post('/api/models/scan',json={},headers={'Authorization':header,'X-Prollama-Request':'1'})
            assert r.status==200
