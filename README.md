# AforoDGT — Sistema de Aforo de Tráfico en Galicia

Sistema automático de detección e conteo de vehículos en cámaras de tráfico da DGT en Galicia, con publicación dos resultados en ArcGIS Online.

## Descrición

O sistema obtén imaxes das cámaras de tráfico da DGT en Galicia, aplica un modelo de detección de obxectos (YOLO) para identificar vehículos, e filtra as deteccións estáticas para distinguir vehículos en movemento de vehículos aparcados. Os resultados publícanse de xeito automático nunha capa de ArcGIS Online.

## Funcionamento

1. Obtéñense as cámaras de Galicia da capa DGT mediante a API de ArcGIS
2. Compróbase se cada cámara ten unha imaxe nova (mediante a cabeceira `Last-Modified`)
3. Execútase inferencia YOLO sobre as imaxes novas
4. Aplícase un filtro espacio-temporal para eliminar vehículos aparcados
5. Gárdanse as deteccións en bruto e as estatísticas agregadas en ArcGIS Online
6. Xérase unha imaxe anotada con vehículos en movemento e aparcados

## Estrutura

| Ficheiro | Descrición |
|---|---|
| `update_records.py` | Script principal: inferencia, filtrado e publicación |
| `utils.py` | Funcións auxiliares de acceso a ArcGIS |
| `draw_results_image.py` | Xeración de imaxes anotadas |
| `ema_aggregates.py` | Cálculo de agregados con media móbil exponencial |
| `processing_lock.py` | Bloqueo para evitar execucións simultáneas |
| `logging_settings.py` | Configuración de logs |
| `crear_capas.py` | Creación das capas en ArcGIS Online |

## Instalación

```bash
pip install ultralytics arcgis opencv-python tqdm python-dotenv
```

## Configuración

Crea un ficheiro `.env` na raíz do proxecto:

```
ARCGIS_USERNAME=o_teu_usuario
ARCGIS_PASSWORD=o_teu_contrasinal
```

## Execución

```bash
python update_records.py
```

O script execútase de xeito periódico (p.ex. con Task Scheduler ou cron) e só procesa as cámaras con imaxes novas desde a última execución.

## Requisitos

- Python 3.10+
- GPU recomendada para inferencia (compatible con CUDA)
- Conta en ArcGIS Online con acceso ás capas do proxecto
