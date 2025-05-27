# -*- coding: utf-8 -*-
import math
import pyproj
import traceback # For debug prints in convert_to_utm, if DEBUG_MODE is active
from typing import Optional # Though not explicitly in signatures, good for config.UTMCoordinates

import config # For type hints and DEBUG_MODE

def dms_to_decimal(
    degrees: config.Number,
    minutes: config.Number,
    seconds: config.Number,
    direction: str
) -> float:
    """
    Convierte Grados, Minutos, Segundos (DMS) a Grados Decimales.
    Lança ValueError em caso de erro de conversão ou direção inválida.
    """
    try:
        deg_f = float(getattr(degrees, 'real', degrees))
        min_f = float(getattr(minutes, 'real', minutes))
        sec_f = float(getattr(seconds, 'real', seconds))

        if not all(math.isfinite(x) for x in [deg_f, min_f, sec_f]):
            raise ValueError(
                f"Componente(s) DMS no finito: D={degrees}, M={minutes}, S={seconds}"
            )
        if not (0 <= min_f < 60 and 0 <= sec_f < 60):
            print(
                f"\nWarning: Valores DMS fuera del range (Min={min_f}, Sec={sec_f}), "
                "continuando cálculo."
            )
        dd = deg_f + min_f / 60.0 + sec_f / 3600.0
        direction_upper = direction.upper()
        if direction_upper in ['S', 'W']:
            return -dd
        if direction_upper in ['N', 'E']:
            return dd
        raise ValueError(f"Dirección GPS desconocida: '{direction}'")
    except (ValueError, TypeError, AttributeError) as e:
        raise ValueError(
            f"Error convirtiendo DMS ({degrees}, {minutes}, {seconds}, {direction}): {e}"
        ) from e

def convert_to_utm(latitude: float, longitude: float) -> config.UTMCoordinates:
    # (Función sin cambios recientes, pero incluida por completitud)
    # ... (Código completo de convert_to_utm de la v2.1-alpha.5 / v2.2-debug.1) ...
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)): print(f"\nError UTM: Latitud/Longitud no numérica ({type(latitude)}, {type(longitude)})"); return None, None, None, None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180): print(f"\nError UTM: Coordenadas Lat/Lon fuera de rango ({latitude}, {longitude})"); return None, None, None, None
    epsg_code = 0 
    try:
        zone = math.floor((longitude + 180) / 6) + 1; hemisphere = 'N' if latitude >= 0 else 'S'
        epsg_code_base = 32600 if latitude >= 0 else 32700; epsg_code = epsg_code_base + zone
        crs_wgs84 = pyproj.CRS("EPSG:4326"); crs_utm = pyproj.CRS(f"EPSG:{epsg_code}")
        transformer = pyproj.Transformer.from_crs(crs_wgs84, crs_utm, always_xy=True)
        easting, northing = transformer.transform(longitude, latitude)
        if not math.isfinite(easting) or not math.isfinite(northing): raise ValueError(f"Resultado da transformação UTM não finito: E={easting}, N={northing}")
        return easting, northing, zone, hemisphere
    except pyproj.exceptions.CRSError as e_crs:
        epsg_str = f"EPSG:{epsg_code}" if epsg_code != 0 else "EPSG desconocido"
        print(f"\nError UTM: Problema com o sistema de coordenadas ({epsg_str}): {e_crs}"); return None, None, None, None
    except ValueError as e_val: print(f"\nError UTM: Problema nos valores durante a conversão: {e_val}"); return None, None, None, None
    except Exception as e: # pylint: disable=broad-except
        if config.DEBUG_MODE: traceback.print_exc()
        print(f"\nError inesperado en la conversión UTM para ({latitude}, {longitude}): {e}"); return None, None, None, None
