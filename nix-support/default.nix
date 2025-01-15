{pkgs ? import <nixpkgs> {}, ...}: let
    env = pkgs.python311.withPackages (import ./dependencies.nix { inherit pkgs; });
in pkgs.stdenv.mkDerivation {
    pname = "stregsystemet";
    version = "latest";
    src = ../.;

    installPhase = ''
        mkdir -p $out/bin
        mkdir -p $out/share/stregsystemet

        cp local.cfg.skel local.cfg
        echo "${env.interpreter} $out/share/stregsystemet/manage.py \$@" > $out/bin/stregsystemet
        sed -i '1 i #!${pkgs.bash}/bin/bash' $out/bin/stregsystemet
        chmod +x $out/bin/stregsystemet

        sed -i '1d' manage.py

        cp ./* $out/share/stregsystemet -r
    '';
}
