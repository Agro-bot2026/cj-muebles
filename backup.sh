#!/bin/bash
# Backup CJ Muebles → Google Drive
set -e
APP=/root/cj-muebles
FECHA=$(date +%F_%H%M)
TMP=/tmp/cjbackup-$FECHA
mkdir -p $TMP

# Lo único con estado: base de datos, .env y archivos subidos
cp $APP/muebleria.db $TMP/ 2>/dev/null || true
cp $APP/.env $TMP/ 2>/dev/null || true
tar czf $TMP/uploads.tar.gz -C $APP/static uploads 2>/dev/null || true

# Empaquetar todo y subir
tar czf /tmp/cjbackup-$FECHA.tar.gz -C /tmp cjbackup-$FECHA
rclone copy /tmp/cjbackup-$FECHA.tar.gz gdrive:backups-cjmuebles/

# Limpiar temporales locales
rm -rf $TMP /tmp/cjbackup-$FECHA.tar.gz

# Retención: borrar backups de más de 30 días en Drive
rclone delete --min-age 30d gdrive:backups-cjmuebles/ 2>/dev/null || true

echo "Backup $FECHA subido a gdrive:backups-cjmuebles/"
