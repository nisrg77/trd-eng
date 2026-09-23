module.exports = {
  apps: [
    {
      name: "tedeng-backend",
      script: "services/run_backend.py",
      interpreter: "python", // Uses global python or virtualenv if activated
      watch: false,
      instances: 1,
      autorestart: true,
      max_memory_restart: "1G",
      env: {
        NODE_ENV: "production",
      }
    },
    {
      name: "tedeng-ws",
      script: "services/ws_server.py",
      interpreter: "python",
      watch: false,
      instances: 1,
      autorestart: true,
      env: {
        NODE_ENV: "production",
      }
    },
    {
      name: "tedeng-orchestrator",
      script: "execution/trade_engine_orchestrator.py",
      interpreter: "python",
      watch: false,
      instances: 1,
      autorestart: true,
      env: {
        NODE_ENV: "production",
      }
    },
    {
      name: "tedeng-screener",
      script: "data_pipeline/stock_screener.py",
      interpreter: "python",
      watch: false,
      autorestart: false,
      cron_restart: "15 08 * * 1-5", // Runs at 8:15 AM Mon-Fri
      instances: 1
    }
  ]
};
