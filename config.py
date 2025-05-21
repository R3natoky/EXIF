# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# config.py
#
# Archivo de configuración para el proyecto procesador_exif.
# Contiene constantes globales, definiciones de tags y tipos.
# -----------------------------------------------------------------------------

from PIL import ExifTags as PIL_ExifTags
from typing import Optional, Dict, Any, Tuple, List, Union
import math # Necesario para algunas constantes como math.inf si se usaran

# --- MODO DE DEPURACIÓN ---
DEBUG_MODE: bool = False # Cambiar a True para activar logs de depuración

# --- Constantes para Tags EXIF ---
# Es importante que PIL_ExifTags se importe y use aquí para definir TAGS y GPSTAGS
_TAGS_INTERNAL: Dict[int, str] = PIL_ExifTags.TAGS
TAGS: Dict[int, str] = {v: k for k, v in _TAGS_INTERNAL.items()}
GPSTAGS: Dict[int, str] = PIL_ExifTags.GPSTAGS
DATETIME_TAG_ID: Optional[int] = TAGS.get("DateTime") # Originalmente 306

GPS_IFD_TAG_ID: Optional[int] = TAGS.get("GPSInfo")
ORIENTATION_TAG_ID: Optional[int] = TAGS.get("Orientation")
IMAGE_DESCRIPTION_TAG_ID: Optional[int] = TAGS.get("ImageDescription")
DATETIME_ORIGINAL_TAG_ID: Optional[int] = TAGS.get("DateTimeOriginal")
DATETIME_TAG_ID: Optional[int] = TAGS.get("DateTime")

# --- Constantes para Salida Excel ---
EXCEL_IMAGE_COL: int = 0      # Coluna A para imagen
EXCEL_NAME_COL: int = 1       # Coluna B para Nombre (nuevo)
EXCEL_DESC_COL: int = 2       # Coluna C para Descripción
EXCEL_DATA_START_COL: int = 1 # Dados textuais começam na coluna B (índice 1)

EXCEL_TARGET_IMAGE_WIDTH_PX: int = 250
EXCEL_TEMP_IMAGE_SCALE_FACTOR: float = 1.5
EXCEL_TEMP_IMAGE_QUALITY: int = 90
EXCEL_COL_WIDTH_FACTOR: float = 0.15
EXCEL_ROW_HEIGHT_FACTOR: float = 0.75

# --- Constantes para Salida KMZ ---
KMZ_IMAGE_WIDTH: int = 400
KMZ_IMAGE_QUALITY: int = 85

# NUEVAS CONSTANTES PARA XPTitle (Nome Personalizado)
# ID del tag XPTitle. piexif lo maneja como piexif.ExifIFD.XPTitle.
# Su valor decimal es 40091.
NOME_PERSONALIZADO_TAG_ID = 315
# XP_TITLE_TAG_ID: int = 40091 # ESTE TAG NOFUNCIONA
# Clave que usaremos en el diccionario PhotoInfo y en los datos EXIF decodificados.
PHOTO_INFO_CUSTOM_NAME_KEY: str = "custom_name"

# --- Tipos para Type Hinting ---
# Estos son alias de tipo que se usarán a través del proyecto.
ExifData = Dict[str, Any]
Coordinates = Optional[Tuple[float, float]]
UTMCoordinates = Optional[Tuple[float, float, int, str]]
# PhotoInfo se usará mucho, es bueno tenerlo definido centralmente.
PhotoInfo = Dict[str, Any]
Number = Union[int, float]

if DEBUG_MODE:
    print("DEBUG [config.py]: MODO DEPURACIÓN ACTIVO.")
    print("DEBUG [config.py]: Constantes y diccionarios TAGS definidos.")
    # Pequeña verificación de que los tags importantes se cargaron (opcional)
    if GPS_IFD_TAG_ID is None:
        print("DEBUG [config.py]: Advertencia - TAGS.get('GPSInfo') devolvió None. Verifica la instalación de Pillow o los nombres de los tags.")
    if ORIENTATION_TAG_ID is None:
        print("DEBUG [config.py]: Advertencia - TAGS.get('Orientation') devolvió None.")