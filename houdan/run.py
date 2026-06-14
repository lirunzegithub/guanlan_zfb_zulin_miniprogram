"""观澜数码租赁后端启动入口"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=True)
