"""更新 Nginx 配置并测试（自动SSH密钥认证）"""
import paramiko, time, os

host = '139.199.69.88'

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
# 自动SSH密钥认证
key_path = os.path.expanduser('~/.ssh/id_rsa')
key = paramiko.RSAKey.from_private_key_file(key_path)
c.connect(host, username='ubuntu', pkey=key, timeout=15)
print('SSH密钥认证成功')

def run(cmd, wait=1):
    print(f'  RUN: {cmd[:80]}')
    stdin, stdout, stderr = c.exec_command(cmd)
    time.sleep(wait)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if err:
        print(f'  ERR: {err[:200]}')
    if out:
        print(f'  OUT: {out[:300]}')
    return out

nginx_conf = '''server {
    listen 80;
    listen [::]:80;
    server_name lvbaixing.top www.lvbaixing.top 139.199.69.88;

    client_max_body_size 10M;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }

    location /app/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    location / {
        return 301 /app/;
    }
}'''

# Write nginx config
print('1. 更新 Nginx 配置...')
cmd = f"sudo tee /etc/nginx/conf.d/lvbai.conf << 'EOF'\n{nginx_conf}\nEOF"
run(cmd)

print()
print('2. 测试 Nginx 配置...')
run('sudo nginx -t 2>&1')

print()
print('3. 重载 Nginx...')
run('sudo systemctl reload nginx 2>&1')

print()
print('4. 测试 IPv6 域名...')
run('curl -s -o /dev/null -w "%{http_code}" http://lvbaixing.top/api/health')

print()
print('5. 测试 IPv4 IP...')
run('curl -s http://139.199.69.88/api/health')

print()
print('6. 检查监听端口...')
run('sudo ss -tlnp | grep -E ":80|:8000"')

c.close()
print()
print('完成!')