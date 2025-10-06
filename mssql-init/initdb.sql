-- mssql-init/initdb.sql
:setvar DB_NAME "ProleitProductionDB"
:setvar RESTORE_FILE "/var/opt/mssql/backups/dbldc_backup_031025.bak"
:setvar APP_LOGIN "edmund"
:setvar APP_PASSWORD "ChangeMe!234"

-- ↑ hodnoty můžeš přepsat z CLI (-v) nebo z Compose (viz níže)

-------------------------------------------------------------------------------

DECLARE @db sysname      = N'$(DB_NAME)';
DECLARE @bak nvarchar(4000) = N'$(RESTORE_FILE)';

-- Pokud DB už existuje, jen ji necháme být
IF DB_ID(@db) IS NOT NULL
BEGIN
    PRINT CONCAT('Database ', @db, ' already exists. Skipping restore.');
    GOTO CreateLoginUser;
END

-- Získání logical names z .bak
CREATE TABLE #fl
(
  LogicalName sysname,
  PhysicalName nvarchar(4000),
  [Type] char(1),
  FileGroupName sysname NULL,
  Size numeric(20,0) NULL,
  MaxSize numeric(20,0) NULL,
  FileId int NULL,
  CreateLSN numeric(25,0) NULL,
  DropLSN numeric(25,0) NULL,
  UniqueId uniqueidentifier NULL,
  ReadOnlyLSN numeric(25,0) NULL,
  ReadWriteLSN numeric(25,0) NULL,
  BackupSizeInBytes bigint NULL,
  SourceBlockSize int NULL,
  FileGroupId int NULL,
  LogGroupGUID uniqueidentifier NULL,
  DifferentialBaseLSN numeric(25,0) NULL,
  DifferentialBaseGUID uniqueidentifier NULL,
  IsReadOnly bit NULL,
  IsPresent bit NULL,
  TDEThumbprint varbinary(32) NULL,
  SnapshotUrl nvarchar(4000) NULL
);

DECLARE @cmd nvarchar(max) = N'RESTORE FILELISTONLY FROM DISK = N''' + REPLACE(@bak,'''','''''') + N'''';
INSERT INTO #fl EXEC (@cmd);

DECLARE @dataLogical sysname = (SELECT TOP 1 LogicalName FROM #fl WHERE [Type] = 'D' ORDER BY FileId);
DECLARE @logLogical  sysname = (SELECT TOP 1 LogicalName FROM #fl WHERE [Type] = 'L' ORDER BY FileId);

IF @dataLogical IS NULL OR @logLogical IS NULL
BEGIN
    RAISERROR('Cannot detect logical names from backup file.',16,1);
    RETURN;
END

DECLARE @dataTarget nvarchar(4000) = N'/var/opt/mssql/data/' + @db + N'.mdf';
DECLARE @logTarget  nvarchar(4000) = N'/var/opt/mssql/data/' + @db + N'_log.ldf';

DECLARE @restore nvarchar(max) =
   N'RESTORE DATABASE [' + @db + N'] FROM DISK = N''' + REPLACE(@bak,'''','''''') + N''' ' +
   N'WITH MOVE N''' + @dataLogical + N''' TO N''' + @dataTarget + N''', ' +
   N'     MOVE N''' + @logLogical  + N''' TO N''' + @logTarget  + N''', ' +
   N'     REPLACE, RECOVERY, STATS=5;';

PRINT @restore;
EXEC (@restore);

-- volitelné: nastavení vlastníka a kompatibility
EXEC (N'ALTER AUTHORIZATION ON DATABASE::[' + @db + N'] TO sa;');
EXEC (N'ALTER DATABASE [' + @db + N'] SET COMPATIBILITY_LEVEL = 160;');

CreateLoginUser:
-- Vytvoř aplikační login/user (pokud není prázdný)
DECLARE @login sysname      = NULLIF(N'$(APP_LOGIN)',    N'');
DECLARE @password nvarchar(200) = NULLIF(N'$(APP_PASSWORD)', N'');

IF @login IS NOT NULL AND @password IS NOT NULL
BEGIN
    IF NOT EXISTS (SELECT 1 FROM sys.sql_logins WHERE name = @login)
        EXEC (N'CREATE LOGIN [' + @login + N'] WITH PASSWORD = N''' + REPLACE(@password,'''','''''') + N''', CHECK_POLICY = OFF;');

    IF DB_ID(@db) IS NOT NULL
    BEGIN
        DECLARE @sql nvarchar(max) = N'USE [' + @db + N']; ' +
           N'IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N''' + REPLACE(@login,'''','''''') + N''') ' +
           N'   CREATE USER [' + @login + N'] FOR LOGIN [' + @login + N']; ' +
           N'EXEC sp_addrolemember N''db_owner'', N''' + REPLACE(@login,'''','''''') + N''';';
        EXEC (@sql);
    END
END

PRINT 'Init script finished.';
