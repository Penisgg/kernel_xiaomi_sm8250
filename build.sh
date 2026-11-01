#!/bin/bash

KERNEL=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) || exit 1
cd "$KERNEL" || exit 1
source "$KERNEL/../settings.sh" || exit 1

#
#   settings.sh (example)
#
# export VERSION="1.x.x"
# export BUILD=1
# export PREFIX="e"
# export DESC="description"
# export DEVICE="alioth"
# export TGTOKEN=bot_id
# export LAST=last commit hash for generation changelog
# export TYPE="test or early"
# export LEVEL=1
# export EXTRA=""
# export FIE_DEBUG=0 # Set to 1 for /sys/kernel/debug/fie_stats
# export ONLY=""
# export SHAK=hash commit for squash revert KSU
# export SHAB=hash commit for 5k battery
#

MAIN=${MAIN:-/home/timisong}

CLANG=$MAIN/clang
GCC_ARM=$MAIN/arm-linux-androideabi-4.9
GCC_AARCH64=$MAIN/aarch64-linux-android-4.9

check_and_clone() (
    local dir=$1 repo=$2

    if [[ ! -d "$dir" ]]; then
        mkdir -p -- "$(dirname "$dir")" || return 1
        git clone "$repo" "$dir" || return 1
    fi
)

check_and_wget() (
    local dir=$1 repo=$2

    if [[ ! -d "$dir" ]]; then
        mkdir -p -- "$(dirname "$dir")" || return 1
        local tmp
        tmp=$(mktemp -d "${dir}.XXXXXX") || return 1
        trap 'rm -rf -- "$tmp"' EXIT
        wget -O "$tmp/clang.tar.gz" "$repo" || return 1
        tar -xzf "$tmp/clang.tar.gz" -C "$tmp" || return 1
        rm -- "$tmp/clang.tar.gz" || return 1
        mv -- "$tmp" "$dir" || return 1
    fi
)

# Return the actual make/tee status, including when build() is used in an if.
compile_kernel() {
    local -a status
    local -a configs=("${DEVICE}_defconfig" vendor/xiaomi/magictime-common.config)

    if [[ "${FIE_DEBUG:-0}" == 1 ]]; then
        configs+=(vendor/xiaomi/fie-debug.config)
    fi
    make O="$OUT" "${configs[@]}" 2>&1 | tee build.log
    status=("${PIPESTATUS[@]}")
    if (( status[0] || status[1] )); then
        return 1
    fi

    # Remove packaged outputs before make so old images cannot pass validation.
    rm -f -- "$OUT/arch/arm64/boot/Image" \
        "$OUT/arch/arm64/boot/dtbo.img" || return 1
    if [[ -d "$OUT/arch/arm64/boot/dts" ]]; then
        find "$OUT/arch/arm64/boot/dts" -type f -name '*.dtb' -delete || return 1
    fi

    make -j "$(nproc)" O="$OUT" CC="ccache clang" HOSTCC=gcc \
        LD=ld.lld AS=llvm-as AR=llvm-ar NM=llvm-nm \
        OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump STRIP=llvm-strip \
        LLVM=1 LLVM_IAS=1 V="${VERBOSE:-0}" 2>&1 | tee -a build.log
    status=("${PIPESTATUS[@]}")
    (( status[0] == 0 && status[1] == 0 ))
}

stage_kernel() {
    local boot="$OUT/arch/arm64/boot"
    local dtb dtb_list
    local -a dtbs=()

    if [[ ! -s "$boot/Image" || ! -s "$boot/dtbo.img" || ! -d "$boot/dts" ]]; then
        echo "Ошибка: нет Image, DTBO или DTS" >&2
        return 1
    fi
    # Check the producer status too: process substitution would hide failures.
    dtb_list=$(mktemp "$OUT/dtbs.XXXXXX") || return 1
    if ! find "$boot/dts" -type f -name '*.dtb' -print0 > "$dtb_list" ||
       ! LC_ALL=C sort -z -o "$dtb_list" "$dtb_list"; then
        rm -f -- "$dtb_list"
        return 1
    fi
    while IFS= read -r -d '' dtb; do
        if [[ ! -s "$dtb" ]]; then
            rm -f -- "$dtb_list"
            return 1
        fi
        dtbs+=("$dtb")
    done < "$dtb_list"
    rm -- "$dtb_list" || return 1
    if (( ${#dtbs[@]} == 0 )); then
        echo "Ошибка: не найдены DTB текущей сборки" >&2
        return 1
    fi

    mkdir -p -- "$(dirname "$IMG")" "$(dirname "$DTB")" \
        "$(dirname "$DTBO")" || return 1
    cp -- "$boot/Image" "$IMG" || return 1
    cp -- "$boot/dtbo.img" "$DTBO" || return 1
    cat -- "${dtbs[@]}" > "$DTB" || return 1
}

build() {
    local OUT="${OUT_ROOT:-$KERNEL/out}/$DEVICE"
    START=$(date +%s)
    git log $LAST..HEAD > ../changelog.txt
    BRANCH=$(git branch --show-current)

    MAGICTIME=$MAIN/MagicTime-$DEVICE

    ANYKERNEL_LINK=https://github.com/TIMISONG-dev/MagicTime-$DEVICE

    if [ ! -d "$MAGICTIME" ]; then
        mkdir -p "$MAGICTIME" || return 1

        if [ ! -d "$MAGICTIME/Anykernel" ]; then
            git clone "$ANYKERNEL_LINK" "$MAGICTIME/Anykernel" || return 1

            mv "$MAGICTIME/Anykernel/"* "$MAGICTIME/" || return 1

            rm -rf -- "$MAGICTIME/Anykernel"
        fi
    else
        if [ -d "$MAGICTIME/.git" ]; then
            rm -rf -- "$MAGICTIME/.git"
        fi
    fi

    if [ "$DEVICE" = pipa ]; then
        IMG=$MAGICTIME/kernels/Image
        DTB=$MAGICTIME/kernels/dtb
        DTBO=$MAGICTIME/kernels/dtbo.img
    else
        IMG=$MAGICTIME/Image
        DTB=$MAGICTIME/dtb
        DTBO=$MAGICTIME/dtbo.img
    fi

    if ! compile_kernel; then
        echo "Ошибка сборки; упаковка отменена" >&2
        return 1
    fi
    if ! stage_kernel; then
        echo "Ошибка проверки артефактов" >&2
        return 1
    fi

    END=$(date +%s)
    ELAPSED=$((END - START))

    CAPTION="MagicTime ${VERSION}${PREFIX}${BUILD}"
    CAPTION="${CAPTION}"$'\n'"desc: ${DESC}"$'\n'"branch: ${BRANCH}"$'\n'"Длительность: $ELAPSED секунд"
    CHANGELOG="../changelog.txt"

    echo Общее время выполнения: $ELAPSED секунд

    cd "$MAGICTIME" || return 1

    if [ "$TYPE" = "test" ]; then
        7z a -mx9 "MagicTime-$DEVICE-$FILE.zip" * -x!*.zip || return 1
    else
        7z a -mx9 "MagicTime-$DEVICE-$BUILD_DATE.zip" * -x!*.zip || return 1
    fi

    if [ "$TYPE" = "test" ]; then
        curl -s -X POST https://api.telegram.org/bot$TGTOKEN/sendDocument?chat_id=@magictimekernel \
        -F document=@./MagicTime-$DEVICE-$FILE.zip \
        -F caption="${CAPTION}" \
        -F message_thread_id=79346
    else
        curl -s -X POST https://api.telegram.org/bot$TGTOKEN/sendDocument?chat_id=@magictimekernel \
        -F document=@./MagicTime-$DEVICE-$BUILD_DATE.zip \
        -F caption="${CAPTION}" \
        -F message_thread_id=38153
    fi

    if [ "$TYPE" = "early" ] && [ -s "$CHANGELOG" ]; then
        curl -s -X POST https://api.telegram.org/bot$TGTOKEN/sendDocument?chat_id=@magictimekernel \
        -F document=@"$CHANGELOG" \
        -F caption="Changelog" \
        -F message_thread_id=38153
    fi

    if [ "$TYPE" = "test" ]; then
        rm -f -- "MagicTime-$DEVICE-$FILE.zip"
    else
        rm -f -- "MagicTime-$DEVICE-$BUILD_DATE.zip"
    fi

    BUILD=$((BUILD + 1))

    cd "$KERNEL" || return 1
    LAST=$(git log -1 --format=%H)

    sed -i "s/LAST=.*/LAST=$LAST/" ../settings.sh || return 1
    sed -i "s/BUILD=.*/BUILD=$BUILD/" ../settings.sh || return 1
    return 0
}

check_and_wget "$CLANG" \
    https://github.com/liliumproject/clang/releases/download/20250912/lilium_clang-20250912.tar.gz || exit 1
check_and_clone "$GCC_ARM" \
    https://github.com/LineageOS/android_prebuilts_gcc_linux-x86_arm_arm-linux-androideabi-4.9 \
        arm-linux-androideabi-4.9 || exit 1
check_and_clone "$GCC_AARCH64" \
    https://github.com/LineageOS/android_prebuilts_gcc_linux-x86_aarch64_aarch64-linux-android-4.9 \
        aarch64-linux-android-4.9 || exit 1

export PATH=$CLANG/bin:$GCC_AARCH64/bin:$GCC_ARM/bin:$PATH
export ARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-
export CROSS_COMPILE_COMPAT=arm-linux-gnueabi-
export KBUILD_BUILD_USER=TIMISONG
export KBUILD_BUILD_HOST=timisong-dev

BUILD_DATE=$(date '+%Y-%m-%d_%H-%M-%S')

# Early build
if [ $LEVEL = 1 ] && [ $TYPE = early ]; then
    build || exit 1
    clear
fi

# Test builds
if [ "$TYPE" = "test" ]; then
    # Format: "DEVICE:BRANCH:MOD_KSU:MOD_BATTERY:DESC:FILE"
    CONFIGS=(
        "alioth:magictime-new:ksu:stk:POCO F3 AOSP:AOSP-KSU"
        "alioth:magictime-new:no_ksu:stk:POCO F3 AOSP without KSU:AOSP-NONKSU"
        "alioth:magictime-new:ksu:5k:POCO F3 AOSP 5k battery:AOSP-KSU-5K"
        "alioth:magictime-new:no_ksu:5k:POCO F3 AOSP without KSU 5k battery:AOSP-NONKSU-5K"
        "alioth:magictime-miui:ksu:stk:POCO F3 MIUI:MIUI-KSU"
        "alioth:magictime-miui:no_ksu:stk:POCO F3 MIUI without KSU:MIUI-NONKSU"
        "alioth:magictime-miui:ksu:5k:POCO F3 MIUI 5k battery:MIUI-KSU-5K"
        "alioth:magictime-miui:no_ksu:5k:POCO F3 MIUI without KSU 5k battery:MIUI-NONKSU-5K"

        "pipa:magictime-new:ksu:stk:Mi Pad 6 AOSP:AOSP-KSU"
        "pipa:magictime-new:no_ksu:stk:Mi Pad 6 AOSP without KSU:AOSP-NONKSU"
        "pipa:magictime-miui:ksu:stk:Mi Pad 6 MIUI:MIUI-KSU"
        "pipa:magictime-miui:no_ksu:stk:Mi Pad 6 MIUI without KSU:MIUI-NONKSU"

	    "apollo:magictime-new:ksu:stk:Mi 10T AOSP:AOSP-KSU"
	    "apollo:magictime-new:no_ksu:stk:Mi 10T AOSP without KSU:AOSP-NONKSU"
        "apollo:magictime-miui:ksu:stk:Mi 10T MIUI:MIUI-KSU"
	    "apollo:magictime-miui:no_ksu:stk:Mi 10T MIUI without KSU:MIUI-NONKSU"
    )

    if [ -n "$ONLY" ]; then
        TARGET_CONFIGS=()

        if [[ "$ONLY" =~ ^[0-9]+$ ]]; then
            IDX_ONLY=$((ONLY - 1))
            if [ "$IDX_ONLY" -ge 0 ] && [ "$IDX_ONLY" -lt "${#CONFIGS[@]}" ]; then
                TARGET_CONFIGS+=("${CONFIGS[$IDX_ONLY]}")
            else
                echo "Ошибка: ONLY=$ONLY выходит за массив (элементов: ${#CONFIGS[@]})"
                exit 1
            fi
        else
            for cfg in "${CONFIGS[@]}"; do
                if [[ "$cfg" == *"$ONLY"* ]]; then
                    TARGET_CONFIGS+=("$cfg")
                fi
            done
        fi

        if [ "${#TARGET_CONFIGS[@]}" -eq 0 ]; then
            echo "Ошибка: Нет конфигураций, соответствующих ONLY='$ONLY'"
            exit 1
        fi

        CONFIGS=("${TARGET_CONFIGS[@]}")
        LEVEL=1
    fi

    while true; do
        IDX=$((LEVEL - 1))

        if [ "$IDX" -ge "${#CONFIGS[@]}" ]; then
            if [ -z "$ONLY" ]; then
                LEVEL=1
                EXTRA=""
                sed -i "s/LEVEL=.*/LEVEL=1/" ../settings.sh
                sed -i "s/EXTRA=.*/EXTRA=\"\"/ " ../settings.sh
            fi
            git checkout magictime-new >/dev/null 2>&1
            git reset --hard origin/magictime-new >/dev/null 2>&1
            clear
            exit 0
        fi

        IFS=':' read -r DEVICE BRANCH MOD_KSU MOD_BATTERY DESC FILE <<< "${CONFIGS[$IDX]}"

        echo "=== Сборка уровня $LEVEL / ${#CONFIGS[@]}: $DESC ==="

        git checkout "$BRANCH" >/dev/null 2>&1
        git fetch origin "$BRANCH" >/dev/null 2>&1 || true
        git reset --hard "origin/$BRANCH" >/dev/null 2>&1

        if [ "$MOD_BATTERY" = "5k" ]; then
            git cherry-pick "$SHAB" >/dev/null 2>&1
            if [ $? -ne 0 ]; then
                git cherry-pick --abort >/dev/null 2>&1
                exit 1
            fi
        fi

        if [ "$MOD_KSU" = "no_ksu" ]; then
            git cherry-pick "$SHAK" >/dev/null 2>&1
            if [ $? -ne 0 ]; then
                git cherry-pick --abort >/dev/null 2>&1
                exit 1
            fi
        fi

        if [ "$EXTRA" = "!4" ]; then
            git cherry-pick "$SHAK" || true
        elif [ "$EXTRA" = "!10" ]; then
            git cherry-pick "$SHAK" || true
        fi

        if build; then
            NEXT_LEVEL=$((LEVEL + 1))
            sed -i "s/LEVEL=.*/LEVEL=$NEXT_LEVEL/" ../settings.sh
            LEVEL=$NEXT_LEVEL
            clear
        else
            echo "Ошибка сборки на уровне $LEVEL ($DESC)"
            exit 1
        fi
    done
fi
