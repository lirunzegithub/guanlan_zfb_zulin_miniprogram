# rsa_keys/ — 支付宝接入密钥

本目录存放支付宝开放平台对接所需的 RSA 密钥。**真实密钥已被 `.gitignore` 排除，不会进入版本库。**

需要放置 3 个文件（仓库里提供了对应的 `.example` 占位示例）：

| 文件 | 说明 | 从哪来 |
|---|---|---|
| `app_private_key.pem`   | 你的**应用私钥**（PKCS#8 或 PKCS#1 均可） | 支付宝开放平台密钥工具生成，自己保管 |
| `app_public_key.pem`    | 你的应用公钥 | 同上，上传到开放平台换取支付宝公钥 |
| `alipay_public_key.pem` | **支付宝公钥** | 开放平台「接口加签方式」里下载 |

## 操作步骤

1. 用[支付宝密钥生成工具](https://opendocs.alipay.com/common/02kipl)生成 RSA2 应用密钥对。
2. 把应用公钥上传到开放平台，下载平台返回的「支付宝公钥」。
3. 将 3 个 PEM 文件按上表命名后放进本目录（去掉 `.example` 后缀的真实文件）。
4. 路径在 `app/config.py` 的 `APP_PRIVATE_KEY_PATH` / `ALIPAY_PUBLIC_KEY_PATH` 里配置，默认即指向本目录。

> ⚠️ 私钥是敏感凭据，切勿提交到任何公开仓库。`.gitignore` 已默认忽略 `*.pem`。
