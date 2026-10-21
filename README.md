# ACLOPI Annecy – Plataforma de simulación

Gemelo digital de una planta (monorriel) en NetLogo 6.4.0 (`model/Paper.nlogo`), ejecutado en modo headless desde Python con pynetlogo.

## Requisitos

- Windows 11
- Python 3.12 de 64 bits (el venv debe crearse con `py -3.12`, no con el Python por defecto del sistema)
- NetLogo 6.4.0 instalado en `C:\Program Files\NetLogo 6.4.0`

## Configuración del entorno (PowerShell)

Todos los comandos se ejecutan desde la raíz del repositorio.

Crear el entorno virtual:

```powershell
py -3.12 -m venv .venv
```

Activarlo (si PowerShell bloquea el script, ejecuta antes `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`):

```powershell
.\.venv\Scripts\Activate.ps1
```

Instalar las dependencias:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Crear el archivo `.env` a partir de la plantilla y ajustar las rutas si NetLogo está en otro sitio:

```powershell
Copy-Item .env.example .env
```

## Smoke test

Comprueba que NetLogo arranca en modo headless, carga el modelo, ejecuta `setup` y 100 ticks:

```powershell
python scripts\smoke_test.py
```

Las carpetas de salida `Results/Data` y `Results/Events` se crean dentro de `model/`, porque NetLogo resuelve las rutas relativas respecto a la carpeta del modelo.
