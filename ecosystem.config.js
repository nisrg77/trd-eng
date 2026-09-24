module.exports = {
  apps: [
    {
      name: "tedeng-backend",
      script: "services/run_backend.py",
      interpreter: "venv/Scripts/python.exe", // Windows local env, adjust for prod
      watch: false,
      instances: 1,
      autorestart: true,
      max_memory_restart: "1G",
      env: {
        NODE_ENV: "development",
      },
      env_production: {
        NODE_ENV: "production",
      }
    },
    {
      name: "tedeng-ws",
      script: "services/ws_server.py",
      interpreter: "venv/Scripts/python.exe",
      watch: false,
      instances: 1,
      autorestart: true,
      env: {
        NODE_ENV: "development",
      }
    },
    {
      name: "tedeng-frontend",
      script: "npm",
      args: "run dev",
      cwd: "./frontend",
      watch: false,
      instances: 1,
      autorestart: true,
      env: {
        NODE_ENV: "development",
        PORT: 3000
      },
      env_production: {
        NODE_ENV: "production",
        args: "run start"
      }
    },
    {
      name: "tedeng-orchestrator",
      script: "execution/trade_engine_orchestrator.py",
      interpreter: "venv/Scripts/python.exe",
      watch: false,
      instances: 1,
      autorestart: true,
      env: {
        NODE_ENV: "development",
      }
    },
    {
      name: "tedeng-screener",
      script: "data_pipeline/stock_screener.py",
      interpreter: "venv/Scripts/python.exe",
      watch: false,
      autorestart: false,
      cron_restart: "15 08 * * 1-5", // Runs at 8:15 AM Mon-Fri (15 mins before CME open proxy)
      instances: 1
    }
  ]
};
