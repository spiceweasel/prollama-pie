import json
import os
import signal
from pathlib import Path
import pytest
from pro_llama.common import allowed_ports, atomic_json, read_json
from pro_llama.gguf import estimate_kv
from pro_llama.nginx_apply import render
from pro_llama.supervisor import Supervisor, build_argv

HERE = Path(__file__).parent

def test_ports_and_json(tmp_path):
    assert allowed_ports({"ranges": [[8080,8082]], "sets": [9000]}) == [8080,8081,8082,9000]
    with pytest.raises(ValueError): allowed_ports({"ranges": [[70000,70001]]})
    dest=tmp_path/'x.json'
    atomic_json(dest, {"k": 1})
    assert read_json(dest)=={"k":1}

def test_kv_formula():
    m={"general.architecture":"llama","llama.block_count":32,"llama.embedding_length":4096,
       "llama.attention.head_count":32,"llama.attention.head_count_kv":8}
    assert estimate_kv(m, 4096) == 4096*32*8*(128*2+128*2)
    assert estimate_kv({},8192) is None

def test_render_nginx_cert_and_conflicts(tmp_path):
    cert=tmp_path/'cert.crt'; key=tmp_path/'cert.key'; cert.write_text('fake'); key.write_text('fake')
    opts={"admin_public_port":8443,"admin_backend_port":18765,"cert":str(cert),"key":str(key),"server_name":"llama.home.arpa"}
    content=render(opts, {"routes":[{"public_port":8080,"backend_port":18080},{"public_port":8081,"backend_port":18081}]})
    assert 'listen 0.0.0.0:8080 ssl;' in content
    assert 'proxy_pass http://127.0.0.1:18080;' in content
    assert 'proxy_buffering off;' in content
    assert 'proxy_set_header Host $http_host;' in content
    assert 'ssl_protocols TLSv1.2 TLSv1.3;' in content
    with pytest.raises(ValueError): render(opts, {"routes":[{"public_port":8080,"backend_port":18080},{"public_port":8080,"backend_port":18081}]})
    with pytest.raises(ValueError): render(opts, {"routes":[{"public_port":18080,"backend_port":18080}]})

@pytest.mark.asyncio
async def test_supervisor_persistence_drain_and_scene(tmp_path):
    fake=HERE/'fake_llama_server.py'
    model=tmp_path/'tiny.gguf'; model.write_bytes(b'GGUFjunk')
    keys=tmp_path/'keys'; keys.write_text('fake-token')
    config={"binary":str(fake),"model_dirs":[str(tmp_path)],"state_dir":str(tmp_path/'state'),
            "admin_port":18765,"socket":str(tmp_path/'sock'),
            "public_ports":{"ranges":[[26080,26085]],"sets":[]},
            "backend_ports":{"ranges":[[26180,26185]],"sets":[]},
            "nginx_apply_command":[],"require_model_api_keys":True,
            "default_model_api_key_file":str(keys),
            "profiles":{"cpu":{"description":"cpu","env":{"HIP_VISIBLE_DEVICES":""},"gpu_ids":[]}}}
    sup=Supervisor(config)
    sup.add_model({"id":"tiny","path":str(model),"card":{"notes":"test"}})
    item=await sup.start({"name":"one","model_id":"tiny","profile":"cpu","launch":{"gpu_layers":0}})
    try:
        assert item['argv'][1:3] == ['--model',str(model)]
        assert '--api-key-file' in item['argv']
        assert item['public_port']!=item['backend_port']
        assert read_json(tmp_path/'state'/'proxy.json')['routes']==[{"backend_port":item['backend_port'],"public_port":item['public_port']}]
        sup2=Supervisor(config)
        assert sup2.snapshot()['instances']['one']['alive']
        assert sup2.save_running_scene('my-scene')=='my-scene'
        await sup2.stop('one')
        assert read_json(tmp_path/'state'/'proxy.json') == {'routes':[]}
        for _ in range(8):
            await sup2.poll()
            if sup2.state['instances']['one']['status']=='stopped': break
        assert sup2.state['instances']['one']['status']=='stopped'
    finally:
        if sup.state['instances']['one'].get('pid'):
            try: os.killpg(item['pid'],signal.SIGKILL)
            except ProcessLookupError: pass
