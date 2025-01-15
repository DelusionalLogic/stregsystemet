{pkgs ? import <nixpkgs> {}, ...}:

pkgs.mkShell {
    packages = ((import ./dependencies.nix { inherit pkgs; }) pkgs.python311Packages) ++ [pkgs.mailhog pkgs.black];
}
