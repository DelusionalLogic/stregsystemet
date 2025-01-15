{pkgs}: let
    # Based on requirements.txt, determine dependencies to fetch from nixpkgs
    requirements = ../requirements.txt;
    # Read file and split it into lines
    lines = pkgs.lib.lists.remove "" (pkgs.lib.strings.splitString "\n" (builtins.readFile requirements));
    packages = map (pkg: builtins.elemAt (pkgs.lib.strings.splitString "==" pkg) 0) lines;
    filteredPackages = builtins.filter (pkg: pkg != "Django-Select2") packages;
in py: [(pkgs.callPackage ./django-select2.nix { inherit pkgs py; })] ++ map (pkg: py.${pkgs.lib.toLower pkg}) filteredPackages