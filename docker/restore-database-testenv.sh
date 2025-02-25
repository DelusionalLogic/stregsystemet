#!/bin/bash
#
# Script for setting up docker-stregsystem and reloading prod-database dump

# be verbose
set -x

# path to mysql dump file after extraction from backup
database_dump_path=stregsystem-db-2021-09-24.txt

# password to use to restore backup
mysql_root_password=juststars

# set to empty (sudo='') if sudo is not required for your docker installation
sudo='sudo '

# flush and setup environment 
$sudo docker-compose down && sudo docker-compose up -d

printf "Wait for MySQL to start up in database [assuming 20s]\n"
sleep 20

# remember to put "use stregsystem;" in backup before running
printf -- "--\n-- Restore hotfix, must use stregsystem\n--\n\nuse stregsystem;\n" | cat - $database_dump_path | $sudo docker exec -i docker_db_1 sh -c "exec mysql -uroot -p$mysql_root_password"
