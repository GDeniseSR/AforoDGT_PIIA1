from arcgis.features import FeatureLayerCollection
from arcgis.gis import GIS

gis = GIS("home")

camera_layer_definition = {
    "name": "aforo_camaras_dgt",
    "displayField": "NAMEUNIT",
    "hasAttachments": True,
    "geometryType": "esriGeometryPoint",
    "objectIdField": "OBJECTID",
    "spatialReference": {"wkid": 4326, "latestWkid": 4326},
    "drawingInfo": {
        "renderer": {
            "type": "simple",
            "symbol": {
                "type": "esriSMS",
                "style": "esriSMSCircle",
                "color": [196, 252, 202, 255],
                "size": 4,
                "angle": 0,
                "xoffset": 0,
                "yoffset": 0,
                "outline": {"color": [0, 0, 0, 255], "width": 0.7}
            }
        },
        "scaleSymbols": True,
        "transparency": 0,
        "labelingInfo": None
    },
    "fields": [
        {"name": "OBJECTID",           "type": "esriFieldTypeOID",     "alias": "OBJECTID",           "sqlType": "sqlTypeOther", "nullable": False, "editable": False, "domain": None, "defaultValue": None},
        {"name": "id",                 "type": "esriFieldTypeString",  "alias": "id",                 "sqlType": "sqlTypeOther", "length": 2048,  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "pk",                 "type": "esriFieldTypeString",  "alias": "pk",                 "sqlType": "sqlTypeOther", "length": 2048,  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "sentido",            "type": "esriFieldTypeString",  "alias": "sentido",            "sqlType": "sqlTypeOther", "length": 2048,  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "carretera",          "type": "esriFieldTypeString",  "alias": "carretera",          "sqlType": "sqlTypeOther", "length": 2048,  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "provincia",          "type": "esriFieldTypeString",  "alias": "provincia",          "sqlType": "sqlTypeOther", "length": 2048,  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
#        {"name": "latitud",            "type": "esriFieldTypeDouble",  "alias": "latitud",            "sqlType": "sqlTypeOther",                  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
#        {"name": "longitud",           "type": "esriFieldTypeDouble",  "alias": "longitud",           "sqlType": "sqlTypeOther",                  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "imagen",             "type": "esriFieldTypeString",  "alias": "imagen",             "sqlType": "sqlTypeOther", "length": 2048,  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "NATCODE",            "type": "esriFieldTypeString",  "alias": "NATCODE",            "sqlType": "sqlTypeOther", "length": 32,    "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "NAMEUNIT",           "type": "esriFieldTypeString",  "alias": "NAMEUNIT",           "sqlType": "sqlTypeOther", "length": 128,   "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "CODNUT1",            "type": "esriFieldTypeString",  "alias": "CODNUT1",            "sqlType": "sqlTypeOther", "length": 16,    "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "CODNUT2",            "type": "esriFieldTypeString",  "alias": "CODNUT2",            "sqlType": "sqlTypeOther", "length": 16,    "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "CODNUT3",            "type": "esriFieldTypeString",  "alias": "CODNUT3",            "sqlType": "sqlTypeOther", "length": 16,    "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "estado",             "type": "esriFieldTypeString",  "alias": "estado",             "sqlType": "sqlTypeOther", "length": 32,    "nullable": True, "editable": True, "domain": None, "defaultValue": "pendiente"},
        {"name": "timestamp_registro", "type": "esriFieldTypeDate",    "alias": "timestamp_registro", "sqlType": "sqlTypeOther",                  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "num_coches",         "type": "esriFieldTypeInteger", "alias": "num_coches",         "sqlType": "sqlTypeOther",                  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "num_camiones",       "type": "esriFieldTypeInteger", "alias": "num_camiones",       "sqlType": "sqlTypeOther",                  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "num_buses",          "type": "esriFieldTypeInteger", "alias": "num_buses",          "sqlType": "sqlTypeOther",                  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "num_motos",          "type": "esriFieldTypeInteger", "alias": "num_motos",          "sqlType": "sqlTypeOther",                  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "num_bicicletas",     "type": "esriFieldTypeInteger", "alias": "num_bicicletas",     "sqlType": "sqlTypeOther",                  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
        {"name": "total_vehiculos",    "type": "esriFieldTypeInteger", "alias": "total_vehiculos",    "sqlType": "sqlTypeOther",                  "nullable": True, "editable": True, "domain": None, "defaultValue": None},
    ],
    "capabilities": "Create,Delete,Query,Update,Editing"
}

raw_table_definition = {
    "name": "detecciones_raw",
    "type": "Table",
    "objectIdField": "OBJECTID",
    "fields": [
        {"name": "OBJECTID",            "type": "esriFieldTypeOID",     "alias": "OBJECTID",            "sqlType": "sqlTypeOther", "nullable": False, "editable": False, "domain": None, "defaultValue": None},
        {"name": "id_camara",           "type": "esriFieldTypeString",  "alias": "camera_id",           "sqlType": "sqlTypeOther", "length": 2048,  "nullable": False, "editable": True, "domain": None, "defaultValue": None},
        {"name": "timestamp_registro",  "type": "esriFieldTypeDate",    "alias": "timestamp_registro",  "sqlType": "sqlTypeOther",                  "nullable": False, "editable": True, "domain": None, "defaultValue": None},
        {"name": "timestamp_procesado", "type": "esriFieldTypeDate",    "alias": "timestamp_procesado", "sqlType": "sqlTypeOther",                  "nullable": True,  "editable": True, "domain": None, "defaultValue": None},
        {"name": "num_coches",          "type": "esriFieldTypeInteger", "alias": "num_coches",          "sqlType": "sqlTypeOther",                  "nullable": True,  "editable": True, "domain": None, "defaultValue": None},
        {"name": "num_camiones",        "type": "esriFieldTypeInteger", "alias": "num_camiones",        "sqlType": "sqlTypeOther",                  "nullable": True,  "editable": True, "domain": None, "defaultValue": None},
        {"name": "num_buses",           "type": "esriFieldTypeInteger", "alias": "num_buses",           "sqlType": "sqlTypeOther",                  "nullable": True,  "editable": True, "domain": None, "defaultValue": None},
        {"name": "num_motos",           "type": "esriFieldTypeInteger", "alias": "num_motos",           "sqlType": "sqlTypeOther",                  "nullable": True,  "editable": True, "domain": None, "defaultValue": None},
        {"name": "num_bicicletas",      "type": "esriFieldTypeInteger", "alias": "num_bicicletas",      "sqlType": "sqlTypeOther",                  "nullable": True,  "editable": True, "domain": None, "defaultValue": None}
    ],
    "capabilities": "Create,Delete,Query,Update,Editing"
}

ema_table_definition = {
    "name": "detecciones_ema",
    "type": "Table",
    "objectIdField": "OBJECTID",
    "fields": [
        {"name": "OBJECTID",             "type": "esriFieldTypeOID",     "alias": "OBJECTID",             "sqlType": "sqlTypeOther",                 "nullable": False, "editable": False, "domain": None, "defaultValue": None},
        {"name": "id_camara",            "type": "esriFieldTypeString",  "alias": "camera_id",            "sqlType": "sqlTypeOther", "length": 2048, "nullable": False, "editable": True,  "domain": None, "defaultValue": None},
        {"name": "dia_semana",           "type": "esriFieldTypeInteger", "alias": "dia_semana",           "sqlType": "sqlTypeOther",                 "nullable": False, "editable": True,  "domain": None, "defaultValue": None},
        {"name": "timeslot",             "type": "esriFieldTypeString",  "alias": "timeslot",             "sqlType": "sqlTypeOther", "length": 32,   "nullable": False, "editable": True,  "domain": None, "defaultValue": None},
        {"name": "n_observaciones",      "type": "esriFieldTypeInteger", "alias": "n_observaciones",      "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "ultima_actualizacion", "type": "esriFieldTypeDate",    "alias": "ultima_actualizacion", "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "media_coches",         "type": "esriFieldTypeDouble",  "alias": "media_coches",         "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "max_coches",           "type": "esriFieldTypeDouble",  "alias": "max_coches",           "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "media_camiones",       "type": "esriFieldTypeDouble",  "alias": "media_camiones",       "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "max_camiones",         "type": "esriFieldTypeDouble",  "alias": "max_camiones",         "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "media_buses",          "type": "esriFieldTypeDouble",  "alias": "media_buses",          "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "max_buses",            "type": "esriFieldTypeDouble",  "alias": "max_buses",            "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "media_motos",          "type": "esriFieldTypeDouble",  "alias": "media_motos",          "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "max_motos",            "type": "esriFieldTypeDouble",  "alias": "max_motos",            "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "media_bicicletas",     "type": "esriFieldTypeDouble",  "alias": "media_bicicletas",     "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "max_bicicletas",       "type": "esriFieldTypeDouble",  "alias": "max_bicicletas",       "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "media_total",          "type": "esriFieldTypeDouble",  "alias": "media_total",          "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
        {"name": "max_total",            "type": "esriFieldTypeDouble",  "alias": "max_total",            "sqlType": "sqlTypeOther",                 "nullable": True,  "editable": True,  "domain": None, "defaultValue": None},
    ],
    "capabilities": "Create,Delete,Query,Update,Editing"
}

item = gis.content.create_service(
    name="Aforo Cámaras DGT",
    service_type="featureService",
)

flc = FeatureLayerCollection(item.url, gis=gis)
flc.manager.update_definition({
    "spatialReference": {"wkid": 4326, "latestWkid": 4326}
})
flc.manager.add_to_definition({
    "layers": [camera_layer_definition],
    "tables": [raw_table_definition, ema_table_definition]
})
print(f"Created: {item.id} — {item.url}")