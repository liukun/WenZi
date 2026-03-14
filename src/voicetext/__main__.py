"""PyInstaller entry point - uses absolute imports."""



def main():
    from voicetext.app import main as app_main
    app_main()


if __name__ == "__main__":
    main()
