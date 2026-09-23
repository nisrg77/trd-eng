module.exports = {
  apps: [
    {
      name: "tedeng-frontend",
      script: "npm",
      args: "run start",
      cwd: "./frontend",
      watch: false,
      instances: 1,
      autorestart: true,
      env: {
        NODE_ENV: "production",
        PORT: 3000
      }
    }
  ]
};
