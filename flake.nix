{
  description = "MaiMBot Nix Dev Env";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };

        # 读取 requirements.txt 文件
        requirementsFile = builtins.readFile ./requirements.txt;

        # 解析 requirements.txt 文件，提取包名
        parseRequirements = content:
          let
            lines = builtins.split "\n" content;
            # 过滤掉空行和注释
            filteredLines = builtins.filter (line:
              line != "" && !(builtins.match "^ *#.*" line)
            ) lines;
            # 提取包名（去掉版本号）
            packageNames = builtins.map (line:
              builtins.head (builtins.split "[=<>]" line)
            ) filteredLines;
          in
          packageNames;

        # 获取 requirements.txt 中的包名列表
        requirements = parseRequirements requirementsFile;

        # 动态生成 Python 环境
        pythonEnv = pkgs.python3.withPackages (ps:
          builtins.map (pkg: ps.${pkg}) requirements
        );
      in
      {
        devShell = pkgs.mkShell {
          buildInputs = [ pythonEnv ];

          shellHook = ''
            echo "Python environment is ready!"
          '';
        };
      }
    );
}