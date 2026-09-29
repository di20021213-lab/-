Положите сюда установщики программ (.exe, .msi, .msu, .msix, .bat, .cmd, .ps1)
или просто перетащите их в окно Silent Installer.

Имя файла должно подходить под шаблон из programs.json, например:
  7z2409-x64.exe                     -> 7-Zip
  AcroRdrDC2400221005_ru_RU.exe      -> Adobe Acrobat Reader
  googlechromestandaloneenterprise64.msi -> Google Chrome
  npp.8.6.9.Installer.x64.exe        -> Notepad++

Если файла нет в каталоге, программа сама определит тип установщика
(MSI, Inno Setup, NSIS, InstallShield, WiX и др.) и подставит ключи тихой установки.

Установщики, состоящие из нескольких файлов (Adobe Acrobat Pro, Microsoft Office),
кладите в подпапку, например: Distrib\Adobe Acrobat\setup.exe, Distrib\Office\setup.exe
