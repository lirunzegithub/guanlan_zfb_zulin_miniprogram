<div align="center">

# Alipay Credit-Free Deposit · Digital Rental Mini-Program (Full-Stack)

**Alipay Mini-Program frontend + Python (Flask + SQLite) backend + Vue admin panel**
A complete "Zhima Credit deposit-free rental" business system: real-name (KYC) verification, credit-based deposit freeze, pre-authorized debit, order fulfillment sync, logistics, coupons, and an admin dashboard.

[中文](./README.md) · [License](#-license-learning-only-no-commercial-use) · [Commercial License](#-commercial-license-free--lifetime) · [Deployment Service](#-deployment-service)

</div>

---

## ✨ Overview

A full-stack Alipay Mini-Program project for "3C electronics / equipment online rental", built around Alipay Open Platform's **Zhima Credit deposit-free** capability:

- After real-name + face verification, users place orders **with no cash deposit** using their Zhima Credit;
- Merchants close the money loop via **fund authorization freeze / unfreeze** and **pre-auth-to-payment** (rent, damage assessment, overdue fees);
- The full order lifecycle is synced to the **Alipay Order Center** (fulfillment sync); logistics, returns, and inspection flow automatically.

> A complete reference implementation for learning how to integrate Alipay "credit borrow-and-return / deposit-free rental".

## 🖼 Screenshots

### 📱 Mini-Program Frontend (User side)

<table>
  <tr>
    <td align="center"><img src="./assets/front-home.png" width="200"/><br/><sub>Home · banners / trust badges / product feed</sub></td>
    <td align="center"><img src="./assets/front-category.png" width="200"/><br/><sub>Category · keyword search + sidebar</sub></td>
    <td align="center"><img src="./assets/front-product.png" width="200"/><br/><sub>Product · Zhima deposit-free / tiered price</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="./assets/front-service.png" width="200"/><br/><sub>Support · live chat + FAQ</sub></td>
    <td align="center"><img src="./assets/front-mine.png" width="200"/><br/><sub>Profile · orders / KYC / coupons</sub></td>
    <td></td>
  </tr>
</table>

### 🖥 Admin Panel (Merchant side · Vue)

<table>
  <tr>
    <td align="center"><img src="./assets/admin-dashboard.png" width="440"/><br/><sub>Dashboard · product / stock / sales / user stats</sub></td>
    <td align="center"><img src="./assets/admin-products.png" width="440"/><br/><sub>Products · tiered price / deposit / multi-image cover</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="./assets/admin-orders.png" width="440"/><br/><sub>Orders · full flow: freeze → ship → rent → return</sub></td>
    <td align="center"><img src="./assets/admin-settings.png" width="440"/><br/><sub>Settings · free-ship days / freeze mode / support info</sub></td>
  </tr>
</table>

## 🧩 Tech Stack

| Layer | Technology |
|---|---|
| Mini-Program frontend | Alipay Mini-Program native (AXML / ACSS / JS) |
| Backend | Python 3.11 · Flask · flask-cors |
| Storage | SQLite (single file, JSON-payload table schema) |
| Alipay integration | alipay-sdk-python · RSA2 signing · AES content encryption |
| Admin panel | Vue 3 + Vue Router (CDN / runtime SFC compile, no build step) |

## 📂 Repository Structure

```
.
├── qianduan/                  # Alipay Mini-Program frontend
│   ├── app.json / app.js      # entry & global config
│   ├── mini.project.json      # project config (fill in your own appid)
│   ├── pages/                 # pages (home/product/checkout/orders/KYC/coupons…)
│   └── utils/config.js        # backend API base URL (change to your domain)
│
└── houdan/                    # Python backend + admin panel
    ├── run.py                 # entry point
    ├── requirements.txt       # Python dependencies
    ├── rsa_keys/              # Alipay keys (.pem gitignored; see in-dir README)
    ├── data/                  # runtime data (app.db auto-created on first run, gitignored)
    ├── docs/                  # integration / deployment / business-flow docs
    ├── manager/               # Vue admin panel (static assets)
    └── app/
        ├── config.py          # Alipay core config (APPID / domain / SERVICE_ID …)
        ├── settings.py        # operational settings defaults
        ├── alipay_client.py   # Alipay SDK wrapper (freeze / debit / sync / KYC…)
        ├── storage/           # SQLite persistence + seed data
        └── routes/            # business routes
```

## 🚀 Quick Start

### 1. Backend

```bash
cd houdan
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Listens on `http://0.0.0.0:8001` by default. On first run it auto-creates `data/app.db` and loads seed data.

- **Admin panel**: open `http://127.0.0.1:8001/manager`
- **Default admin account**: `admin` / `admin888888` — ⚠️ **Change the password immediately after first login** (Staff Management).

### 2. Configure Alipay (required)

| Item | Location |
|---|---|
| App private key / Alipay public key (`.pem`) | `houdan/rsa_keys/` (see its `README.md`) |
| APPID / SERVICE_ID / AES key / callback domain | `AlipayConfig` in `houdan/app/config.py` |
| Service phone / company name / APPID (operational) | Admin "Settings" page, or defaults in `houdan/app/settings.py` |
| Async notify / compliance link / nginx deploy | see `houdan/docs/DEPLOY_CALLBACK.md` |

### 3. Frontend (Mini-Program)

1. Open the `qianduan/` directory in **Alipay Mini-Program DevTools**;
2. Set your Mini-Program `appid` in `qianduan/mini.project.json`;
3. Change `BASE_URL` in `qianduan/utils/config.js` to your backend's public domain;
4. Compile & preview.

> More integration details in `houdan/docs/`: `ALIPAY_INTEGRATION.md`, `IDENTITY_AND_CREDIT_FLOW.md`, `ORDER_CENTER_SYNC.md`, `DEPLOY_CALLBACK.md`, etc.

## ⚠️ Security & Configuration Notes

All sensitive information has been removed from this repository. In this open-source version the following are **placeholders that you must replace**:

- Alipay `APP_ID`, `SERVICE_ID`, `AES_ENCRYPT_KEY` (all empty)
- Callback domain `NOTIFY_BASE` (`your-domain.example.com`) and inventory-system domain
- Service phone (`400-000-0000`) and company name (placeholder)
- The admin account is a demo weak password — **must be changed**
- `rsa_keys/*.pem`, `data/*.db`, `data/*.json` are all `.gitignore`d and never committed

---

## 📜 License (Learning Only, No Commercial Use)

This project is licensed under **[PolyForm Noncommercial License 1.0.0](./LICENSE)**:

- ✅ **Allowed**: anyone may freely study, research, modify, build upon, and distribute it for **non-commercial purposes**;
- ❌ **Prohibited**: any **commercial use** (for-profit operation, paid services to third parties, bundling into commercial products, etc.).

> PolyForm Noncommercial is a non-commercial license designed specifically for *source code*, fitting code licensing better than CC BY-NC.
> Strictly speaking it is **not an OSI-approved open-source license** (the Open Source Definition forbids restricting fields of use), but it permits free study and non-commercial use.

## 💚 Commercial License (Free · Lifetime)

**If you want to use this project commercially, contact the author on WeChat to get a free lifetime commercial license (no charge).**

<div align="center">

<img src="./assets/wechat-qr.JPG" alt="WeChat QR" width="260" />

**WeChat: 饼干打孔李师傅 (Haikou, Hainan)**
Scan to add, note "Commercial License" (商用授权)

</div>

## 🛠 Deployment Service

Don't want to deal with servers / domains / nginx / Alipay configuration yourself?

**Paid deployment service: ¥150 per deployment** — includes backend go-live, HTTPS, and Alipay callback configuration & testing. Ready to use once done.
Contact via the WeChat above.

---

## Disclaimer

This project is for learning and technical exchange only. Users must ensure they: legally hold Alipay merchant qualifications, comply with the Alipay Open Platform agreements and applicable laws, and properly safeguard keys and user privacy data. The author is not responsible for any consequences arising from use of this project.
