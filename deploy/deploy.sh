#!/bin/bash
# 旅白行 AI 旅行规划 - 一键部署脚本
# 使用方法: chmod +x deploy.sh && sudo bash deploy.sh
set -e

echo "=== 旅白行 AI 旅行规划 部署脚本 ==="

# 1. 创建目录
echo "[1/6] 创建项目目录..."
mkdir -p /opt/lvbai/backend /opt/lvbai/deploy

# 2. 复制后端代码
echo "[2/6] 复制后端代码..."
cp -r backend/*.py /opt/lvbai/backend/

# 3. 复制配置文件
echo "[3/6] 复制配置文件..."
cp deploy/.env.example /opt/lvbai/deploy/.env
cp deploy/lvbai.service /etc/systemd/system/
cp deploy/nginx.conf /etc/nginx/conf.d/lvbai.conf

# 4. 安装 Python 依赖
echo "[4/6] 安装 Python 依赖..."
pip3 install -r backend/requirements.txt

# 5. 配置环境变量（请编辑 /opt/lvbai/deploy/.env 填写真实 API Key）
echo "[5/6] 提示：请编辑 /opt/lvbai/deploy/.env 填写 API Key"
echo "  vi /opt/lvbai/deploy/.env"

# 6. 启动服务
echo "[6/6] 启动服务..."
systemctl daemon-reload
systemctl enable lvbai
systemctl restart lvbai
systemctl restart nginx 2>/dev/null || echo "Nginx 未安装，请先安装: yum install nginx 或 apt install nginx"

echo ""
echo "=== 部署完成! ==="
echo "检查服务状态: systemctl status lvbai"
echo "检查 API: curl http://localhost:8000/api/health"
echo ""
echo "下一步："
echo "1. 编辑 API Key: vi /opt/lvbai/deploy/.env"
echo "2. 安装 Nginx (如未安装)"
echo "3. 配置域名 DNS 解析到本服务器"
echo "4. 申请 SSL 证书: certbot --nginx"
echo "5. 在微信小程序后台配置服务器域名白名单"