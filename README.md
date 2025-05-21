# Procesador de Metadatos EXIF para Imágenes (v2.2)

Este script de Python está diseñado para extraer información de metadatos EXIF de fotografías, con un enfoque en coordenadas geográficas (Latitud/Longitud y UTM), fechas y descripciones. Permite generar diversos formatos de salida como KMZ (para Google Earth), KML simple (compatible con My Maps), CSV y archivos Excel con imágenes embebidas. Adicionalmente, ofrece la funcionalidad de actualizar ciertos tags EXIF en las imágenes (Descripción y un "Nome Personalizado" almacenado en el tag Artist) a partir de un archivo Excel.

## Características Principales

*   **Extracción de Metadatos EXIF:**
    *   Coordenadas Geográficas (Latitud, Longitud).
    *   Conversión a Coordenadas UTM (Este, Norte, Zona, Hemisferio).
    *   Fecha y Hora de la captura (`DateTimeOriginal` o `DateTime`).
    *   Descripción de la Imagen (`ImageDescription`).
    *   "Nome Personalizado" (leído y escrito en el tag `Artist`).
    *   Orientación de la imagen.
*   **Generación de Archivos de Salida:**
    *   **KMZ:** Para visualización en Google Earth, incluye puntos geográficos, información detallada en la burbuja descriptiva e imágenes redimensionadas y orientadas correctamente embebidas. El título del punto prioriza "Nome Personalizado" > Primera línea de Descripción > Nombre de archivo.
    *   **KML Simple:** Similar al KMZ pero sin imágenes embebidas, ideal para importar en servicios como Google My Maps. Misma lógica de priorización para el título del punto.
    *   **CSV:** Tabla con los datos extraídos, incluyendo Nome (Archivo), Nome Personalizado (Artist), Descripcion (EXIF), coordenadas, etc.
    *   **Excel (.xlsx):** Tabla similar al CSV pero con la capacidad de embeber miniaturas de las imágenes (orientadas correctamente) y columnas editables para `NomePersonalizado (Editable)` y `Descripcion (EXIF)`.
*   **Actualización de Metadatos EXIF:**
    *   Permite actualizar el tag `ImageDescription` y el tag `Artist` (usado para "Nome Personalizado") de los archivos de imagen originales basándose en los datos de un archivo Excel previamente generado y modificado por el usuario.

## Requisitos

*   Python 3.7+
*   Las siguientes librerías de Python (se pueden instalar con `pip install -r requirements.txt`):
    *   Pillow (PIL Fork)
    *   simplekml
    *   pandas
    *   openpyxl (para manejo de .xlsx con pandas)
    *   pyproj
    *   piexif (necesario para la actualización de EXIF - Opción 4)

## Instalación de Dependencias

1.  Asegúrate de tener Python 3.7 o superior instalado.
2.  (Recomendado) Crea y activa un entorno virtual:
    ```bash
    python -m venv .venv
    # En Windows:
    .\.venv\Scripts\activate
    # En macOS/Linux:
    source .venv/bin/activate
    ```
3.  Instala las dependencias desde el archivo `requirements.txt` (asegúrate de que este archivo esté actualizado en tu proyecto):
    ```bash
    pip install -r requirements.txt
    ```

## Uso del Script

El script se ejecuta desde la línea de comandos:

```bash
python procesar_exif_v2.2.py
