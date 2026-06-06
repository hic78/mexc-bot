// ecosystem.config.js — C150-OPTIMUS MEXC Bot
// Source de vérité: si dump.pm2 est corrompu ou vide,
// "pm2 start ecosystem.config.js" restaure tout en 1 commande.
module.exports = {
  apps: [{
    name: "mexc-bot",
    script: "/root/mexc-bot/bot.py",
    interpreter: "python3",
    cwd: "/root/mexc-bot",
    watch: false,
    autorestart: true,
    max_restarts: 10000,
    restart_delay: 10000,   // 10s entre restarts (evite spam API MEXC)
    env: {
      PYTHONUNBUFFERED: "1"
      // Autres vars depuis .env (load_dotenv dans config.py)
    },
    log_date_format: "YYYY-MM-DD HH:mm:ss",
    error_file: "/root/mexc-bot/bot_error.log",
    out_file: "/root/mexc-bot/bot_out.log",
    merge_logs: true
  }]
}
