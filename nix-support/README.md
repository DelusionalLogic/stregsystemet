# NixOS options in nixosModule:

| option                                          | type       | default                               |
|-------------------------------------------------|------------|---------------------------------------|
| stregsystemet.enable                            | bool       | false                                 |
| stregsystemet.port                              | int        | 8000                                  |
| stregsystemet.hostnames                         | listOf str | ["127.0.0.1" "localhost"]             |
| stregsystemet.general.secret_key                | str        | "_secret_"                            |
| stregsystemet.general.x_frame_options           | str        | "SAMEORIGIN"                          |
| stregsystemet.debug.debug                       | bool       | false                                 |
| stregsystemet.debug.csrf_cookie_secure          | bool       | false                                 |
| stregsystemet.debug.csrf_cookie_httponly        | bool       | false                                 |
| stregsystemet.debug.session_cookit_secure       | bool       | false                                 |
| stregsystemet.debug.secure_browser_xss_filter   | bool       | false                                 |
| stregsystemet.debug.secure_content_type_nosniff | bool       | false                                 |
| stregsystemet.database.engine                   | str        | "sqlite"                              |
| stregsystemet.database.host                     | str        | ""                                    |
| stregsystemet.database.port                     | int        | -1                                    |
| stregsystemet.database.name                     | str        | db.sqlite3                            |
| stregsystemet.database.user                     | str        | ""                                    |
| stregsystemet.database.password                 | str        | ""                                    |
| stregsystemet.workingDirectory                  | str        | "/var/run/stregsystemet"              |
| stregsystemet.superUsers                        | str        | ["treo"]                              |
| stregsystemet.extraSql                          | listOf str | []                                    |
| stregsystemet.testData.enable                   | bool       | false                                 |
| stregsystemet.testData.fixture                  | path       | ../stregsystem/fixtures/testdata.json |

note: stregsystemet.extraSql only supports sqlite or mysql
