# 异步回调上线走查清单

把 `houdan` 部署到 `https://your-domain.example.com/` 让支付宝能回调进来，按顺序做下面 4 步。

---

## 一、服务器侧 · gunicorn + systemd

### 1.1 装 gunicorn（在你的 venv 里）

```bash
cd ~/houdan
source .venv/bin/activate
pip install gunicorn
```

### 1.2 systemd 服务文件

新建 `/etc/systemd/system/houdan.service`：

```ini
[Unit]
Description=Digital Rental Backend
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/srv/houdan
Environment="PYTHONUNBUFFERED=1"
ExecStart=/srv/houdan/.venv/bin/gunicorn \
    --workers 4 \
    --worker-class sync \
    --bind 127.0.0.1:8001 \
    --access-logfile /var/log/houdan/access.log \
    --error-logfile  /var/log/houdan/error.log \
    --capture-output \
    'app:create_app()'
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /var/log/houdan && sudo chown www-data:www-data /var/log/houdan
sudo systemctl daemon-reload
sudo systemctl enable --now houdan
sudo systemctl status houdan
```

### 1.3 ⚠️ workers ≥ 2 时的并发坑

现在订单状态机用的是**进程内** `ORDERS = list`，4 个 worker 各自一份内存，下单和回调可能落到不同 worker → 状态机错乱。**上线前必须**：

- 短期临时方案：`--workers 1` 启动，单进程没并发问题
- 正确方案：架构审查里的 P0 项 — 把 ORDERS 落到 `JsonRepository`，所有 worker 共享文件

我先按 workers=1 给你顶上去；架构改完再切回 4 worker。

---

## 二、nginx 反代

`/etc/nginx/sites-available/your-domain.example.com`：

```nginx
server {
    listen 80;
    server_name your-domain.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.example.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # ===== 支付宝异步通知（关键） =====
    location /api/alipay/notify/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For  $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
        proxy_request_buffering on;
        # 不要做任何 IP 白名单（支付宝出口 IP 段未公布，靠签名验身份）
        # 不要 301/302 跳转（支付宝不跟随）
        # 不要返回 5xx（除非真崩了），否则会被支付宝按 8 次重试
    }

    # 业务 API + 小程序后台
    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /manager {
        proxy_pass http://127.0.0.1:8001;
    }
    location /manager-assets/ {
        proxy_pass http://127.0.0.1:8001;
    }

    # 落地页
    location /product {
        proxy_pass http://127.0.0.1:8001;
    }

    location / {
        return 404;
    }
}
```

证书一键签：

```bash
sudo snap install certbot --classic
sudo certbot --nginx -d your-domain.example.com
sudo nginx -t && sudo systemctl reload nginx
```

---

## 三、支付宝控制台配置（关键，少这一步回调不会来）

### 3.1 全局兜底 NOTIFY_URL

[open.alipay.com](https://open.alipay.com) → 我的应用 → APPID `2021000000000000` → 应用详情 → **网关&回调地址** → 异步通知地址 填：

```
https://your-domain.example.com/api/alipay/notify/auth_freeze
```

> 一个应用只能配 1 个全局 NOTIFY_URL，作兜底。SDK 调用时通过 `req.notify_url` 显式指定的子路径优先生效。

### 3.2 验证 SDK 自动注入（已实现）

`alipay_client.py:160-161` 已经在每次 `freeze` 时自动塞 `req.notify_url = NOTIFY_URL_AUTH_FREEZE`。
后续接 unfreeze / refund / order.pay 等接口时，记得在对应 SDK 包装方法里也 `req.notify_url = ...`。

### 3.3 上传 / 校对应用公钥

如果还没上传过：应用详情 → 接口加签方式 → 公钥模式 → 把 `rsa_keys/app_public_key.pem` 文件正文（去掉 BEGIN/END 头尾的 base64）粘进去 → 保存。

### 3.4 信用服务守约链接

控制台 → 信用服务管理 → SERVICE_ID `20260000000000000000000000` → 守约链接 填：

```
alipays://platformapi/startapp?appId=2021000000000000&page=pages/order-detail/order-detail&query=id=${out_order_no}
```

`${out_order_no}` 是支付宝占位符，**保留原样**。

---

## 四、上线后真机联调

### 4.1 健康检查

```bash
# 本地通
curl -I http://127.0.0.1:8001/api/alipay/notify/auth_freeze  # 应 405（GET 不允许）

# 公网通
curl -I https://your-domain.example.com/api/alipay/notify/auth_freeze  # 应 405

# 无签名（模拟假通知）
curl -X POST https://your-domain.example.com/api/alipay/notify/auth_freeze \
  --data "out_order_no=TEST&status=SUCCESS"  # 应纯文本 "fail"
```

### 4.2 真机回调链路

1. 在支付宝里打开你的小程序 → 加默认地址 → 选商品 → 立即租赁
2. 选租期 → 跳订单详情 → 自动唤起 my.tradePay → **看到 FaceID/密码框** = 我们的 freeze 成功签发 orderStr
3. 完成支付 → 几秒内服务端收到 notify → tail 日志看：
   ```bash
   sudo journalctl -u houdan -f | grep alipay-notify
   ```
   期望出现：
   ```
   [alipay-notify] ch=auth_freeze verify=True biz=True mode=real fields={'notify_id':...}
   ```
4. 订单详情页刷新 → status 从 `audit` 变 `awaiting_face`，开始 15 分钟倒计时

### 4.3 失败排查

| 现象 | 排查 |
|---|---|
| 真机 my.tradePay 报错 ALI64 等 | 私钥/公钥不对，重新比对 `rsa_keys/` 文件 |
| 收银台能拉起但服务端没收 notify | 1) nginx 日志看请求有没到；2) 控制台 NOTIFY_URL 是否填错；3) 证书是否过期 |
| 服务端日志 `verify=False` | 支付宝公钥用错了（用了应用公钥）；或验签字符串拼接被中间件改了 |
| 订单状态没推进 | 业务异常被吞，看 stderr 后面的 `biz err: xxx` |

---

## 五、当前一定还差的事

| # | 待办 | 优先级 |
|---|---|---|
| 1 | gunicorn `--workers 1` 顶上（避免内存 ORDERS 错乱） | 上线前 |
| 2 | 订单存储从 `list` 换成 `JsonRepository`（后续 4 worker） | 上线一周内 |
| 3 | `notify_dedup` 内存 set 换 Redis SETNX（防进程重启丢去重） | 灰度后 |
| 4 | 接入 `unfreeze / refund / auth.pay` 的 SDK 调用 + 自动注入对应 notify_url | 用到时再做 |
| 5 | 给每条回调写 DB 日志表 `notify_log`（事后对账） | 灰度后 |
| 6 | 移除 git 里的 `rsa_keys/`（架构审查 P0 安全项） | 立刻 |
