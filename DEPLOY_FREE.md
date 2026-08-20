# Free deployment

## Render
1. Upload this project to a GitHub repository.
2. Render Dashboard -> New -> Web Service -> connect the repository.
3. Runtime Python, Build: `pip install -r requirements.txt`, Start: `gunicorn app:app`, Plan: Free.
4. Render provides an HTTPS `onrender.com` URL.

## Important
This build still uses SQLite/local uploads. Render Free web services have ephemeral filesystems, so SQLite data and uploaded photos can be lost on restart/redeploy/spin-down. Do NOT use this exact build for permanent cooperative financial records. Migrate the database to a persistent managed PostgreSQL service and photos to persistent object storage before real use.

Initial admin: admin / admin123. Change this immediately after deployment.
