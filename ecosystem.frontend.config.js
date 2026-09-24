module.exports = {
  apps: [
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
        args: "run start",
        PORT: 3000
      }
    }
  ]
};
