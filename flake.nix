{
  description = "Windhover — run large MoE models on a consumer machine with ~25 GB RAM";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        # Python with the packages needed by the offline converter tools
        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          torch
          safetensors
          huggingface-hub
          numpy
          tokenizers
          datasets
        ]);

        windhover = pkgs.stdenv.mkDerivation {
          pname = "windhover";
          version = "1.0";
          src = ./.;

          nativeBuildInputs = [ pkgs.makeWrapper ];

          buildInputs = [
            pkgs.gcc
            pkgs.gmp
          ];

          # Use x86-64-v3 (AVX2) for a portable binary; override with ARCH=native for local builds
          ARCH = "x86-64-v3";

          buildPhase = ''
            runHook preBuild
            make -C c glm ARCH="$ARCH"
            runHook postBuild
          '';

          installPhase = ''
            runHook preInstall
            mkdir -p $out/bin
            cp c/glm $out/bin/glm

            # Wrap coli (the Python CLI) so it finds the right python and the engine
            mkdir -p $out/share/windhover
            cp c/coli $out/share/windhover/coli
            chmod +x $out/share/windhover/coli
            cp -r c/tools $out/share/windhover/tools

            makeWrapper ${pythonEnv}/bin/python $out/bin/coli \
              --add-flags "$out/share/windhover/coli" \
              --set PYTHONPATH "${pythonEnv}/${pkgs.python3.sitePackages}"
            runHook postInstall
          '';

          checkPhase = ''
            runHook preCheck
            cd c
            make test-c
            cd ..
            runHook postCheck
          '';

          doCheck = true;

          meta = with pkgs.lib; {
            description = "Run GLM-5.2 (744B MoE) on a consumer machine with ~25 GB RAM";
            homepage = "https://github.com/cliclye/Windhover";
            license = licenses.asl20;
            platforms = platforms.linux;
            mainProgram = "glm";
          };
        };
      in
      rec {
        packages = {
          default = windhover;
          inherit windhover;
        };

        apps = {
          default = {
            type = "app";
            program = "${windhover}/bin/glm";
          };
          coli = {
            type = "app";
            program = "${windhover}/bin/coli";
          };
        };

        devShells.default = pkgs.mkShell {
          inputsFrom = [ windhover ];

          packages = [
            pythonEnv
            pkgs.gcc
            pkgs.gnumake
            pkgs.clang-tools          # clangd / clang-tidy for IDE support
            pkgs.pkg-config
          ];

          shellHook = ''
            echo "🐦 Windhover dev shell"
            echo "  gcc: $(gcc --version | head -1)"
            echo "  python: $(python3 --version)"
            echo ""
            echo "Build the engine:   make -C c glm"
            echo "Run the converter:  python c/coli convert --model /path/to/glm52_i4"
            echo "Chat:               COLI_MODEL=/path/to/glm52_i4 ./c/glm ..."
          '';
        };
      }
    );
}
