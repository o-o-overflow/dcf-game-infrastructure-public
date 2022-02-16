#!/bin/bash -e

REGISTRY=registry.31337.ooo:5000

only_service=""
do_push=false
restart_pods=false

if [[ $# -ne 0 ]]; then

    while [[ $# -gt 0 ]]
    do
        key="$1"

        case $key in
            -p|--push)
                do_push=true
            ;;
            -s|--service)
                shift
                only_service+=" ${1}"
            ;;
             -r|--restart-pods)
                restart_pods=true
            ;;
            -h|--help)
                printf $' This script builds frontends, builds dockers, and deploys\n'
                printf $' -p, --push \tpushes to production\n -s, --service <service_name> \tproviding this arg limits built services'
                printf $'to base and provided service names\n\t--service may be provided multiple times \n'
				printf $' -r, --restart-pods \trestarts the k8s pods running this service \n'
                printf $'example: ./deploy.sh --frontend --push --service team-interface \n\tBuilds frontend, pushes to production but only for team-interface'

                exit 0
            ;;
            *)
                echo -e "${key} is unknown parameter"
            ;;
        esac
        shift # past argument or value
    done

fi


echo "First build base"
docker build -f "dockerfiles/Dockerfile.game-infrastructure-base" -t "game-infrastructure-base" .
docker tag game-infrastructure-base:latest $REGISTRY/game-infrastructure-base:latest
if [[ ${do_push} = true ]]; then
    docker push $REGISTRY/game-infrastructure-base:latest
fi

for DOCKERFILE in dockerfiles/Dockerfile.*
do
    SERVICE_NAME="${DOCKERFILE##*.}"

    if [ "$SERVICE_NAME" = "game-infrastructure-base" ]; then
        continue
    fi

    if [[ -z "${only_service}" ]] || [[ ${only_service} =~ (^| )"${SERVICE_NAME}"($| ) ]]; then
        echo "Building and deploying ${DOCKERFILE} for ${SERVICE_NAME}"
    else
        continue
    fi


	docker build -f "$DOCKERFILE" -t "$SERVICE_NAME" .
	docker tag $SERVICE_NAME:latest $REGISTRY/$SERVICE_NAME:latest
	if [[ ${do_push} = true ]]; then
	    docker push $REGISTRY/$SERVICE_NAME:latest
        if [[ ${restart_pods} = true ]]; then
            echo "Restarting ${SERVICE_NAME} pod"
            pod_names=$(kubectl get pod -n default -o=custom-columns=NAME:.metadata.name | egrep ${SERVICE_NAME})
            for pod_nm in ${pod_names}; do
                echo kubectl delete pod -n default ${pod_nm}
                kubectl delete pod -n default ${pod_nm}
            done
        fi
    fi
done

sleep 2

if [[ ${restart_pods} = true ]]; then
    kubectl get pod -n default -o=custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,IP:.status.podIP,STATUS:.status.phase
fi


