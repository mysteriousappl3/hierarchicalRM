# VSCode and Linux Intellisense
The following instructions are adapted from [here](https://forum.unity.com/threads/solved-unity-with-vs-code-and-intellisense-on-linux-mint.986088/))

1. Install VS Studio from .deb file (https://code.visualstudio.com/docs/setup/linux)
2. Open VS Code and install de C# extension OmniSharp (you will be asked to install it when you open VS Code). After tah close VS Code
2. Install .net SDK from here: https://docs.microsoft.com/es-es/dotnet/core/install/linux-ubuntu#2004-
3. Install latest Mono release (Ubuntu 20.04): https://www.mono-project.com/download/vs/
    But the following line must be changed: \
    deb https://download.mono-project.com/repo/ubuntu vs-focal main \
    for this one: \
    deb [arch=amd64] https://download.mono-project.com/repo/ubuntu vs-focal main \
    (just added [arch=amd64] ) \
    then `sudo apt install mono-complete` \

4. Open VS Code, go to menu File - Preferences - Settings - Extension - C# configuration
look for "Omnisharp: Use Global Mono", and set it to "always".
5. Close VS Code
6. Go to Unity menu Edit - Preferences - External Tools - External Script Editor, and pick "Visual Studio Code"
7. In the same window, check "Embedded packages", "Local packages", "Built-in packages", "Git packages" and after click on "Regenerate project files"
8. You might need to reboot to get everything working.