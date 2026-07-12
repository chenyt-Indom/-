#!/bin/bash
# 行旅白 AI 旅行规划 - 一键部署脚本
# 域名: lvbaixing.top
# 使用方法: chmod +x deploy.sh && sudo bash deploy.sh
set -e

echo "=== 行旅白 AI 旅行规划 部署脚本 ==="

# 1. 创建目录
echo "[1/6] 创建项目目录..."
mkdir -p /opt/lvbai/backend/static /opt/lvbai/deploy

# 2. 复制后端代码
echo "[2/6] 复制后端代码..."
cp -r backend/*.py /opt/lvbai/backend/
cp -r backend/static/* /opt/lvbai/backend/static/

# 3. 复制配置文件
echo "[3/6] 复制配置文件..."
cp deploy/.env.example /opt/lvbai/deploy/.env
cp deploy/lvbai.service /etc/systemd/system/
cp deploy/nginx.conf /etc/nginx/conf.d/lvbai.conf

# 4. 安装 Python 依赖
echo "[4/6] 安装 Python 依赖..."
pip3 install -r backend/requirements.txt

# 5. 配置环境变量
echo "[5/6] 提示：请编辑 /opt/lvbai/deploy/.env 填写真实 API Key"
echo "  vi /opt/lvbai/deploy/.env"

# 6. 启动服务
echo "[6/6] 启动服务..."
systemctl daemon-reload
systemctl enable lvbai
systemctl restart lvbai

# 配置 Nginx
if command -v nginx &> /dev/null; then
    nginx -t && systemctl restart nginx
    echo "Nginx 已重启"
else
    echo "Nginx 未安装，请安装: apt install nginx"
fi

echo ""
echo "=== 部署完成! ==="
echo "访问地址: http://lvbaixing.top"
echo "API 健康检查: curl http://localhost:8000/api/health"
echo ""
echo "下一步："
echo "1. 编辑 API Key: vi /opt/lvbai/deploy/.env"
echo "2. 配置域名 DNS A 记录指向本服务器 IP"
echo "3. 安装 SSL 证书: certbot --nginx -d lvbaixing.top -d www.lvbaixing.top"
echo "4. 在微信小程序后台配置服务器域名白名单: https://lvbaixing.top"