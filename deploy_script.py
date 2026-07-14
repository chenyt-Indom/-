"""服务器部署脚本（自动SSH密钥认证）"""
import paramiko, time, sys, os

host = '139.199.69.88'

def run(c, cmd, wait=1):
    print(f'  RUN: {cmd[:80]}...')
    stdin, stdout, stderr = c.exec_command(cmd)
    time.sleep(wait)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if err and 'WARNING' not in err:
        print(f'  ERR: {err[:200]}')
    if out:
        print(f'  OUT: {out[:300]}')
    return out, err

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
# 自动SSH密钥认证
key_path = os.path.expanduser('~/.ssh/id_rsa')
key = paramiko.RSAKey.from_private_key_file(key_path)
c.connect(host, username='ubuntu', pkey=key, timeout=15)
print('SSH密钥认证成功\n')

# 1. git pull
print('1. 更新代码...')
run(c, 'git config --global --add safe.directory /opt/lvbai')
run(c, 'cd /opt/lvbai && sudo git pull 2>&1')

# 2. 创建 .env（从本地 .env 读取密钥）
print('2. 创建 .env...')
# 读取本地 .env 文件中的密钥
env_path = os.path.join(os.path.dirname(__file__), 'deploy', '.env')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        env_content = f.read()
    # 将 .env 内容写入服务器
    escaped = env_content.replace("'", "'\\''")
    run(c, f"sudo bash -c \"echo '{escaped}' > /opt/lvbai/deploy/.env\"")
    run(c, 'cat /opt/lvbai/deploy/.env')
else:
    print('  警告：未找到本地 deploy/.env 文件，跳过')

# 3. 安装依赖
print('3. 安装 Python 依赖...')
run(c, 'sudo pip3 install fastapi uvicorn httpx python-dotenv 2>&1', 5)

# 4. 确保 static 目录存在
print('4. 检查 static 目录...')
run(c, 'ls /opt/lvbai/backend/static/ 2>&1')

# 5. 读取 lvbai.service 检查内容
print('5. 检查 service 文件...')
run(c, 'cat /opt/lvbai/deploy/lvbai.service')

# 6. 复制 service 并启动
print('6. 配置并启动服务...')
run(c, 'sudo cp /opt/lvbai/deploy/lvbai.service /etc/systemd/system/')
run(c, 'sudo systemctl daemon-reload')
run(c, 'sudo systemctl stop lvbai 2>/dev/null; echo done')
run(c, 'sudo systemctl enable lvbai 2>&1')
run(c, 'sudo systemctl start lvbai 2>&1')

# 7. 状态
print('7. 服务状态...')
run(c, 'sudo systemctl status lvbai --no-pager -l 2>&1 | head -20')

# 8. Nginx
print('8. 配置 Nginx...')
run(c, 'sudo cp /opt/lvbai/deploy/nginx.conf /etc/nginx/conf.d/lvbai.conf 2>&1')
run(c, 'sudo nginx -t 2>&1')
run(c, 'sudo systemctl restart nginx 2>&1')

# 9. 验证
print('9. 验证...')
run(c, 'curl -s http://localhost:8000/api/health')

c.close()
print('\n部署完成！')