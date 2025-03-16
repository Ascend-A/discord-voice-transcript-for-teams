{pkgs}: {
  deps = [
    pkgs.libtool
    pkgs.ocamlPackages.ffmpeg
    pkgs.ffmpeg
    pkgs.libopus
    pkgs.libsodium
  ];
}
