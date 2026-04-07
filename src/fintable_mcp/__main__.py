"""Entry point for running fintable-mcp as a module: python -m fintable_mcp"""

from .server import mcp

def main():
    mcp.run()

if __name__ == "__main__":
    main()
