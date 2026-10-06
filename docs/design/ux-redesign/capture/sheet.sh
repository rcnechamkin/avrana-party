# usage: sheet.sh out.png in1.png in2.png ...  (tiles images side by side, 390px wide each, padded to 860 high)
out="$1"; shift; n=$#; args=""; f=""; i=0
for p in "$@"; do args="$args -i $p"; f="$f[$i]scale=390:-2,pad=400:860:5:0:0x333333[s$i];"; i=$((i+1)); done
lab=""; for j in $(seq 0 $((n-1))); do lab="$lab[s$j]"; done
ffmpeg -loglevel error -y $args -filter_complex "${f}${lab}hstack=inputs=$n" "$out"
