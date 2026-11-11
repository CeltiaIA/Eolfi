import argparse

from notas.almacen import Almacen


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="notas")
    p.add_argument("--archivo", default="notas.json")
    sub = p.add_subparsers(dest="orden", required=True)
    sub.add_parser("listar")
    an = sub.add_parser("anadir")
    an.add_argument("texto")
    args = p.parse_args(argv)
    almacen = Almacen(args.archivo)
    if args.orden == "anadir":
        print(almacen.anadir(args.texto))
    else:
        for n in almacen.todas():
            print(n)
    return 0
