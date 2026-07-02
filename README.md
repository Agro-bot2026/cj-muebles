# CJ Muebles

Web + panel admin + chatbot IA para muebleria.
Todo lo que se carga en el panel arma la web automaticamente.

## Stack
FastAPI + SQLite + Jinja2 - Chatbot DeepSeek - Nginx + PM2 + Cloudflare

## Funciones
- Web publica: catalogo marketplace, buscador, filtros, ofertas, WhatsApp
- Panel admin dark: productos con fotos/video, categorias, ajustes
- Chatbot IA: responde sobre productos y contacto usando lo cargado
- Seguridad: rate-limit, anti-fuerza bruta, headers HTTP, HTTPS
- SEO: sitemap, robots.txt, Open Graph, PWA

## Variables .env
- SECRET_KEY - clave de sesiones
- DEEPSEEK_API_KEY - API key del chatbot

## Backup
backup.sh respalda db + .env + uploads a Google Drive. Cron diario 3 AM.

## Panel
/admin - usuario inicial admin (cambiar clave en Ajustes)

---
CHARLY_TRICKS DEV
