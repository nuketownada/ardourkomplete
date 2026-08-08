{
  description =
    "Development shell for building Ardour from a git checkout, for the Komplete Kontrol A61 control-surface work.";

  # Pinned to the same nixpkgs revision the host system uses, so every build
  # input is already realised in the store and `nix develop` opens instantly
  # rather than rebuilding a toolchain. Bump deliberately, not casually.
  inputs.nixpkgs.url =
    "github:NixOS/nixpkgs/0ad6f47ea4fe188f4bc8f0380f93ae8523337c6c";

  outputs =
    { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems =
        f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
    in
    {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          name = "ardour-dev";

          # Everything nixpkgs' own ardour build needs. Notably this already
          # includes hidapi and libusb1, which gate the HID and USB control
          # surfaces in libs/surfaces/wscript -- without them our surface
          # would be silently skipped at configure time.
          inputsFrom = [ pkgs.ardour ];

          packages = with pkgs; [
            ccache
            gdb
            git
            pkg-config
            python3      # waf is Python; Ardour vendors ./waf in-tree
          ];

          # nixpkgs sets these in its ardour derivation; a devShell does not
          # inherit them, and the build fails without them.
          #   _GNU_SOURCE  -> ioprio_set syscall
          #   serd/sratom/sord include dirs -> versioned subdirectories that
          #   the compiler does not find on its own
          NIX_CFLAGS_COMPILE = toString [
            "-D_GNU_SOURCE"
            "-I${pkgs.lib.getDev pkgs.serd}/include/serd-0"
            "-I${pkgs.lib.getDev pkgs.sratom}/include/sratom-0"
            "-I${pkgs.lib.getDev pkgs.sord}/include/sord-0"
          ];
          LINKFLAGS = "-lpthread";

          shellHook = ''
            # nixpkgs carries as-flags.patch for this: with AS set, waf's asm
            # task passes -D defines to the assembler and libs/ardour fails to
            # build. Upstream only redefines the asm rule for mingw. Clearing
            # AS avoids needing to patch the tree, which keeps the checkout
            # clean for PRs.
            unset AS

            echo "ardour-dev shell"
            echo "  configure:  ./waf configure --cxx17 --no-phone-home --ptformat"
            echo "  build:      ./waf -j$(nproc)"
            echo "  run:        ./gtk2_ardour/ardev"
            echo
            echo "  surfaces are gated in libs/surfaces/wscript:"
            echo "    hidapi  $(pkg-config --modversion hidapi-hidraw 2>/dev/null || echo '(in-tree)')"
            echo "    libusb  $(pkg-config --modversion libusb-1.0 2>/dev/null || echo MISSING)"
          '';
        };
      });

      formatter = forAllSystems (pkgs: pkgs.nixfmt-rfc-style);
    };
}
