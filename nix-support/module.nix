{config, pkgs, lib, ...}:

with lib.types; {
    options.stregsystemet = {
        enable = lib.mkOption {
            type = bool;
            default = false;
        };
        port = lib.mkOption {
            type = int;
            default = 8000;
        };
        hostnames = lib.mkOption {
            type = listOf str;
            default = ["127.0.0.1" "localhost"];
        };
        general = {
            secret_key = lib.mkOption {
                type = str;
                default = "_secret_";
            };
            x_frame_options = lib.mkOption {
                type = str;
                default = "SAMEORIGIN";
            };
        };
        debug = {
            debug = lib.mkOption {
                type = bool;
                default = false;
            };
            csrf_cookie_secure = lib.mkOption {
                type = bool;
                default = false;

            };
            csrf_cookie_httponly = lib.mkOption {
                type = bool;
                default = false;
            };
            session_cookit_secure = lib.mkOption {
                type = bool;
                default = false;
            };
            secure_browser_xss_filter = lib.mkOption {
                type = bool;
                default = false;
            };
            secure_content_type_nosniff = lib.mkOption {
                type = bool;
                default = false;
            };
        };
        database = {
            engine = lib.mkOption {
                type = str;
                default = "sqlite";
            };
            host = lib.mkOption {
                type = str;
                default = "";
            };
            port = lib.mkOption {
                type = int;
                default = -1;
            };
            name = lib.mkOption {
                type = str;
                default = "db.sqlite3";
            };
            user = lib.mkOption {
                type = str;
                default = "";
            };
            # insecure, would probably we wise to rethink this design
            password = lib.mkOption {
                type = str;
                default = "";
            };
        };
        workingDirectory = lib.mkOption {
            type = str;
            default = "/var/run/stregsystemet";
        };
        superUsers = lib.mkOption {
            type = listOf str;
            default = ["treo"];
        };
        extraSql = lib.mkOption {
            type = listOf str;
            default = [];
        };
        testData = {
            enable = lib.mkOption {
                type = bool;
                default = false;
            };
            fixture = lib.mkOption {
                type = path;
                default = ../stregsystem/fixtures/testdata.json;
            };
        };

    };

    config = {
        systemd.services = let
            stregsystemet = import ./default.nix { inherit pkgs; };
            cfg = config.stregsystemet;
            workingDirectory = pkgs.stdenv.mkDerivation {
                name = "Working Directory";
                version = "0.0";
                src = ../.;
                installPhase = ''
                    #!/usr/bin/env bash
                    mkdir $out
                    cp -r $src/* $out
                    cp ${pkgs.writeText "local.cfg" ''
                        [general]
                        SECRET_KEY=${cfg.general.secret_key}
                        X_FRAME_OPTIONS=${cfg.general.x_frame_options}
    
                        [debug]
                        DEBUG=${if cfg.debug.debug then "True" else "False"}
                        CSRF_COOKIE_SECURE=${if cfg.debug.csrf_cookie_secure then "True" else "False"}
                        CSRF_COOKIE_HTTPONLY=${if cfg.debug.csrf_cookie_httponly then "True" else "False"}
                        SESSION_COOKIT_SECURE=${if cfg.debug.session_cookit_secure then "True" else "False"}
                        SECURE_BROWSER_XSS_FILTER=${if cfg.debug.secure_browser_xss_filter then "True" else "False"}
                        SECURE_CONTENT_TYPE_NOSNIFF=${if cfg.debug.secure_content_type_nosniff then "True" else "False"}
    
                        [database]
                        ENGINE=${cfg.database.engine}
                        PORT=${builtins.toString cfg.database.port}
                        HOST=${cfg.database.host}
                        NAME=${cfg.database.name}
                        USER=${cfg.database.user}
                        PASSWORD=${cfg.database.password}
    
                        [hostnames]
                        ${
                            let
                                f = index: "${builtins.toString index}=${builtins.elemAt cfg.hostnames index}";
                                length = builtins.length cfg.hostnames;
                            in builtins.concatStringsSep "\n" (map f (lib.range 0 (length - 1)))
                        }
                    ''} $out/local.cfg
                '';
            };
            testDataInit = if cfg.testData.enable then ''
                ${stregsystemet}/bin/stregsystemet loaddata ${cfg.testData.fixture}
            '' else ''
                ${builtins.concatStringsSep "\n" (map (user: "${stregsystemet}/bin/stregsystemet createsuperuser --noinput --username ${user}") cfg.superUsers)}
            '';
            doSQL = sql: if cfg.database.engine == "sqlite" then
                ''${pkgs.sqlite}/bin/sqlite ${cfg.workingDirectory}/${cfg.database.name} "${sql}"''
            else if cfg.databse.engine == "mysql" then
                ''${pkgs.mysql}/bin/mysql --user ${cfg.database.user} -p ${cfg.database.password} -e "${sql}"''
            else
                ''echo "${cfg.database.engine} is unsupported for option stregsystemet.extraSql"'';
        in lib.mkIf cfg.enable {
            stregsystemet = {
                enable = true;
                serviceConfig = {
                    WorkingDirectory = "${cfg.workingDirectory}";
                    ExecStart = "${stregsystemet}/bin/stregsystemet runserver ${builtins.toString cfg.port}";
                    Restart = "on-failure";
                };
                wantedBy = ["default.target"];
                after = ["stregsystemet-setup.service"];
            };
            stregsystemet-setup = {
                enable = true;
                serviceConfig = {
                    type = "oneshot";
                    ConditionFirstBoot = "yes";
                    ExecStart = "${pkgs.writeScriptBin "setup.sh" ''
                        #!${pkgs.bash}/bin/bash
                        mkdir ${cfg.workingDirectory}
                        cp -r ${workingDirectory}/* ${cfg.workingDirectory}
                        cd ${cfg.workingDirectory}
                        ${stregsystemet}/bin/stregsystemet migrate
                        ${testDataInit}
                        ${builtins.concatStringsSep "\n" (map doSQL cfg.extraSql)}
                    ''}/bin/setup.sh";
                };
                wantedBy = ["default.target"];
                before = ["stregsystemet.service"];
            };
        };
    };
}
