#!/bin/bash
set +e
SCRIPT_DIR="$(dirname "$0")"

export IMAGE=$1
shift
REGIONS="$@"

if [ -z "$IMAGE" ]; then
    echo "[ERROR] Usage: warmup.sh <IMAGE> <REGION1> [REGION2] ..."
    exit 1
fi

if [ -z "$REGIONS" ]; then
    REGIONS="cn-hangzhou cn-shenzhen cn-beijing cn-shanghai ap-southeast-1"
fi

VERSION=$(echo "$IMAGE" | awk -F: '{print $NF}')
FORMATTED_VERSION=$(echo "$VERSION" | sed 's/\./_/g')
export WARMUP_FUNCTION_NAME="FuncAI-warmup-agent-$FORMATTED_VERSION"

deploy_region() {
    local region=$1
    cd "$SCRIPT_DIR"

    export REGION="$region"
    echo "  [INFO] Deploying warmup function: $WARMUP_FUNCTION_NAME"
    echo "  [INFO] Image: $IMAGE"

    TEMP_LOG="/tmp/warmup_deploy_${region}_$$.log"
    s deploy -y -t s-warmup.yaml --skip-push > "$TEMP_LOG" 2>&1
    local result=$?

    if [ $result -eq 0 ]; then
        FUNCTION_ARN=$(grep "functionArn:" "$TEMP_LOG" | awk '{print $2}' | head -1)
        if [ ! -z "$FUNCTION_ARN" ]; then
            echo "  [SUCCESS] Function deployed: $FUNCTION_ARN"
        else
            FUNCTION_NAME=$(grep "functionName:" "$TEMP_LOG" | awk '{print $2}' | head -1)
            if [ ! -z "$FUNCTION_NAME" ]; then
                echo "  [SUCCESS] Function deployed: $FUNCTION_NAME in $region"
            else
                echo "  [SUCCESS] Function deployed successfully in $region"
            fi
        fi
    else
        echo "  [ERROR] Deployment failed for region $region"
        echo "  [ERROR] Error details:"
        tail -20 "$TEMP_LOG" | sed 's/^/    /'
    fi

    rm -f "$TEMP_LOG"
    return $result
}

REGION_COUNT=0
for region in $REGIONS; do
    REGION_COUNT=$((REGION_COUNT + 1))
done

echo "======================================"
echo "Warmup Image-Gen Agent (Parallel Mode)"
echo "Version: $VERSION"
echo "Image: $IMAGE"
echo "Regions: $REGIONS ($REGION_COUNT regions)"
echo "======================================"

START_TIME=$(date +%s)
COUNT=0
for region in $REGIONS; do
    COUNT=$((COUNT + 1))
    echo "[$COUNT] Starting warmup for region: $region"
    (
        echo "[$COUNT-$region] Process started at $(date '+%H:%M:%S')"
        deploy_region "$region" 2>&1 | sed "s/^/[$COUNT-$region] /"
        echo "[$COUNT-$region] Process finished at $(date '+%H:%M:%S')"
        echo $? > /tmp/warmup_result_${region}.tmp
    ) &
done

echo "All $REGION_COUNT warmup processes started. Waiting for completion..."
echo ""
wait

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo "======================================"
echo "Warmup Summary for version $VERSION"
echo "Total time: ${ELAPSED}s"
SUCCESS_COUNT=0
TOTAL_COUNT=0
for region in $REGIONS; do
    TOTAL_COUNT=$((TOTAL_COUNT + 1))
    if [ -f "/tmp/warmup_result_${region}.tmp" ]; then
        RESULT=$(cat /tmp/warmup_result_${region}.tmp)
        if [ "$RESULT" = "0" ]; then
            SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
            echo "Region $region: SUCCESS"
        else
            echo "Region $region: FAILED (exit code: $RESULT)"
        fi
        rm -f /tmp/warmup_result_${region}.tmp
    else
        echo "Region $region: UNKNOWN (no result file)"
    fi
done
echo "Successful: $SUCCESS_COUNT/$TOTAL_COUNT regions"
if [ $SUCCESS_COUNT -eq $TOTAL_COUNT ]; then
    echo "Status: ALL COMPLETED"
else
    echo "Status: PARTIAL SUCCESS ($((TOTAL_COUNT - SUCCESS_COUNT)) failed)"
fi
echo "======================================"

[ $SUCCESS_COUNT -eq $TOTAL_COUNT ]
