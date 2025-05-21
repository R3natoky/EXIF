# -*- coding: utf-8 -*-
"""
diagnose_exif_tag.py

Script para diagnosticar la lectura de un tag EXIF específico de una imagen,
enfocado en XPTitle y ImageDescription, y listar todos los tags.
"""
import os
from PIL import Image, ExifTags as PILImageExifTags # Renombrado para evitar confusión con piexif.TAGS
from typing import Any, Optional
import piexif
import traceback # Añadido para más detalles en errores

# Importar configuración del proyecto principal si existe para los IDs de tags
try:
    import config # Asume que config.py está en el mismo directorio o en PYTHONPATH
    XP_TITLE_TAG_ID = config.XP_TITLE_TAG_ID
    IMAGE_DESCRIPTION_TAG_ID = config.IMAGE_DESCRIPTION_TAG_ID
except ImportError:
    print("Advertencia: No se pudo importar config.py. Usando IDs de tags por defecto.")
    XP_TITLE_TAG_ID = 40091
    IMAGE_DESCRIPTION_TAG_ID = 270


def decode_bytes_aggressively(byte_string: Optional[bytes], tag_name_hint: str = "") -> Optional[str]:
    """Intenta decodificar una cadena de bytes con varias codificaciones comunes."""
    if not isinstance(byte_string, bytes):
        # print(f"  -> Valor para '{tag_name_hint}' no es bytes, es {type(byte_string)}. No se intenta decodificación agresiva.")
        if isinstance(byte_string, str): return byte_string # Si ya es string, devolverlo
        return None # Devolver None si no es bytes ni string

    print(f"  Intentando decodificaciones agresivas para '{tag_name_hint}' (Valor crudo: {repr(byte_string)[:100]}...):")
    encodings_to_try = [
        'utf-16-le', 'utf-16', 'ucs-2', # Prioridad para tags XP
        'utf-8', 'latin-1', 'cp1252',  # Generales
    ]
    decoded_value = None
    successful_encoding = None
    for enc in encodings_to_try:
        try:
            decoded_value_attempt = byte_string.decode(enc, 'strict')
            # Limpiar caracteres nulos comunes en UTF-16/UCS-2 y espacios
            if enc.startswith('utf-16') or enc == 'ucs-2':
                decoded_value_attempt = decoded_value_attempt.replace('\x00', '')
            decoded_value_attempt = decoded_value_attempt.strip()
            
            if decoded_value_attempt: # Considerar éxito solo si hay contenido después de limpiar
                print(f"    -> Decodificación exitosa con '{enc}': '{decoded_value_attempt}'")
                successful_encoding = enc
                decoded_value = decoded_value_attempt # Asignar el valor decodificado y limpiado
                break 
            else:
                # print(f"    -> Decodificación con '{enc}' resultó en cadena vacía tras limpiar.")
                pass # No es necesario imprimir esto, puede ser verboso
        except UnicodeDecodeError:
            # print(f"    -> Falló decodificación con '{enc}'") # Puede ser verboso
            pass
        except Exception as e:
            print(f"    -> Error inesperado decodificando con '{enc}': {e}")
    
    if successful_encoding:
        return decoded_value
    
    print(f"  -> Todas las decodificaciones específicas para '{tag_name_hint}' fallaron o resultaron vacías. Representación repr: {repr(byte_string)}")
    return None


def analyze_image_exif(image_path: str):
    """Analiza y muestra información sobre XPTitle e ImageDescription."""
    if not os.path.exists(image_path):
        print(f"Error: Archivo no encontrado: {image_path}")
        return

    print(f"\n--- Analizando Imagen: {os.path.basename(image_path)} ---")

    # --- 1. Usando Pillow (PIL.Image.getexif()) ---
    print("\n1. Resultados con Pillow (PIL.Image.getexif()):")
    try:
        img_pil = Image.open(image_path)
        exif_data_pil = img_pil.getexif()

        if not exif_data_pil:
            print("  Pillow: No se encontraron datos EXIF.")
        else:
            print("\n  Listado completo de tags encontrados por Pillow:")
            for tag_id, value in exif_data_pil.items():
                tag_name_pil = PILImageExifTags.TAGS.get(tag_id, f"UnknownTag_{tag_id}")
                print(f"    ID: {tag_id} (Nombre Pillow: {tag_name_pil}) - Tipo: {type(value)} - Valor Crudo: {repr(value)[:150]}")

            raw_xp_title_pil = exif_data_pil.get(XP_TITLE_TAG_ID)
            print(f"\n  Análisis Específico - XPTitle (ID {XP_TITLE_TAG_ID}):")
            print(f"    Valor crudo de Pillow: {repr(raw_xp_title_pil)}")
            print(f"    Tipo de valor crudo: {type(raw_xp_title_pil)}")
            decoded_xp_title_pil = decode_bytes_aggressively(raw_xp_title_pil, "XPTitle (Pillow)")
            print(f"    Resultado decodificación agresiva (XPTitle Pillow): '{decoded_xp_title_pil}'")

            raw_img_desc_pil = exif_data_pil.get(IMAGE_DESCRIPTION_TAG_ID)
            print(f"\n  Análisis Específico - ImageDescription (ID {IMAGE_DESCRIPTION_TAG_ID}):")
            print(f"    Valor crudo de Pillow: {repr(raw_img_desc_pil)}")
            print(f"    Tipo de valor crudo: {type(raw_img_desc_pil)}")
            if isinstance(raw_img_desc_pil, str):
                 print(f"    Valor (ya str, limpiado): '{raw_img_desc_pil.strip()}'")
            else:
                decoded_img_desc_pil = decode_bytes_aggressively(raw_img_desc_pil, "ImageDescription (Pillow)")
                print(f"    Resultado decodificación agresiva (ImageDescription Pillow): '{decoded_img_desc_pil}'")
        
        img_pil.close()
    except Exception as e_pil:
        print(f"  Error procesando con Pillow: {e_pil}")
        traceback.print_exc()

    # --- 2. Usando piexif ---
    print("\n\n2. Resultados con piexif.load():")
    if piexif is None:
        print("  piexif no está instalado. Omitiendo esta sección.")
        return
    try:
        exif_dict_piexif = piexif.load(image_path)
        print("\n  Listado completo de IFDs y tags encontrados por piexif:")
        for ifd_name in exif_dict_piexif:
            if ifd_name in ("thumbnail", "icc_profile"): 
                print(f"    IFD: {ifd_name} (Contenido omitido por brevedad)")
                continue
            print(f"    IFD: {ifd_name}")
            if isinstance(exif_dict_piexif[ifd_name], dict):
                for tag_id, value in exif_dict_piexif[ifd_name].items():
                    tag_name_str = f"UnknownTag_{tag_id}"
                    if ifd_name in piexif.TAGS and tag_id in piexif.TAGS[ifd_name]: # type: ignore
                        tag_name_str = piexif.TAGS[ifd_name][tag_id].get('name', tag_name_str) # type: ignore
                    print(f"      ID: {tag_id} (Nombre piexif: {tag_name_str}) - Tipo: {type(value)} - Valor Crudo: {repr(value)[:150]}")
            else:
                print(f"      Contenido del IFD '{ifd_name}' no es un diccionario: {repr(exif_dict_piexif[ifd_name])[:150]}")
        
        xp_title_piexif_bytes = exif_dict_piexif.get("Exif", {}).get(XP_TITLE_TAG_ID)
        print(f"\n  Análisis Específico - XPTitle (ID {XP_TITLE_TAG_ID} en IFD 'Exif'):")
        print(f"    Valor crudo de piexif: {repr(xp_title_piexif_bytes)}")
        print(f"    Tipo de valor crudo: {type(xp_title_piexif_bytes)}")
        decoded_xp_title_piexif = decode_bytes_aggressively(xp_title_piexif_bytes, "XPTitle (piexif)")
        print(f"    Resultado decodificación agresiva (XPTitle piexif): '{decoded_xp_title_piexif}'")

        img_desc_piexif_bytes = exif_dict_piexif.get("0th", {}).get(IMAGE_DESCRIPTION_TAG_ID)
        print(f"\n  Análisis Específico - ImageDescription (ID {IMAGE_DESCRIPTION_TAG_ID} en IFD '0th'):")
        print(f"    Valor crudo de piexif: {repr(img_desc_piexif_bytes)}")
        print(f"    Tipo de valor crudo: {type(img_desc_piexif_bytes)}")
        decoded_img_desc_piexif = decode_bytes_aggressively(img_desc_piexif_bytes, "ImageDescription (piexif)")
        print(f"    Resultado decodificación agresiva (ImageDescription piexif): '{decoded_img_desc_piexif}'")

    except Exception as e_piexif:
        print(f"  Error procesando con piexif: {e_piexif}")
        traceback.print_exc()
    print("\n--- Análisis Finalizado ---")

if __name__ == "__main__":
    if len(os.sys.argv) < 2:
        print("Uso: python diagnose_exif_tag.py \"/ruta/a/tu/imagen.jpg\"")
        image_file_path = input("Introduce la ruta completa a la imagen a analizar: ").strip('"\' ')
        if not image_file_path:
            print("No se proporcionó ruta. Saliendo.")
            os.sys.exit(1)
    else:
        image_file_path = os.sys.argv[1]
    analyze_image_exif(image_file_path)