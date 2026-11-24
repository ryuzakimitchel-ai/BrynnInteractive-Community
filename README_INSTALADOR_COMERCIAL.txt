BRYNN INTERACTIVE V0.59.0 - INSTALADOR COMERCIAL
=================================================

OBJETIVO
--------
Generar un UNICO archivo EXE para entregar al usuario final:

  installer_output\BrynnInteractive-Setup-0.59.0.exe

El usuario final NO necesita Python, PySide6, PyInstaller, Inno Setup ni el ZIP del proyecto.

COMO GENERARLO
--------------
En tu PC de desarrollo ejecuta:

  crear_instalador_comercial.bat

El script:
1. Compila Brynn Interactive con PyInstaller.
2. Instala Inno Setup 6 mediante winget si hace falta.
3. Empaqueta toda la app en un unico instalador EXE.
4. Abre el Explorador seleccionando el instalador resultante.

EXPERIENCIA DEL CLIENTE
-----------------------
Al ejecutar BrynnInteractive-Setup-0.59.0.exe aparece un asistente de instalacion.

El usuario puede:
- elegir la carpeta de instalacion con Examinar;
- crear opcionalmente un acceso directo en el escritorio;
- instalar un acceso en el Menu Inicio;
- abrir Brynn Interactive al terminar;
- desinstalarlo desde Aplicaciones instaladas de Windows.

La carpeta predeterminada es:
  %LOCALAPPDATA%\Programs\Brynn Interactive

No requiere permisos de administrador para esa ubicacion. Si el usuario elige una ubicacion protegida, Windows/Inno Setup puede solicitar elevacion segun corresponda.

DATOS PERSONALES
----------------
Los datos del streamer NO se guardan dentro de la carpeta de instalacion.
Se mantienen en:
  %APPDATA%\BrynnInteractive

Actualizar o desinstalar la aplicacion no borra esos datos automaticamente.

ICONO DEL INSTALADOR
---------------------
El Setup final usa brynn_default.ico, el mismo icono oficial de Brynn Interactive.
El icono queda incrustado dentro de BrynnInteractive-Setup-0.59.0.exe; no es necesario entregar el archivo .ico al cliente.

