import logging

import requests

api_endpoint = "https://api.elevenlabs.io/v1"
default_headers = {'accept': '*/*'}

def _api_call(requestType, path, headers, jsonData=None, filesData=None) -> requests.Response:
    if path[0] != "/":
        path = "/"+path
    match requestType:
        case "get":
            response = requests.get(api_endpoint + path, headers=headers)
        case "json":
            response = requests.post(api_endpoint + path, headers=headers, json=jsonData)
        case "del":
            response = requests.delete(api_endpoint + path, headers=headers)
        case "multipart":
            if filesData is not None:
                response = requests.post(api_endpoint + path, headers=headers, data=jsonData, files=filesData)
            else:
                response = requests.post(api_endpoint + path, headers=headers, data=jsonData)
        case _:
            raise Exception("Unknown API call type!")

    if response.ok:
        return response
    else:
        pretty_print_POST(response.request)
        responseJSON = response.json()
        raise Exception("Response error!"+
                        "\nDetail: " + str(responseJSON["detail"]))

def api_get(path, headers) -> requests.Response:
    return _api_call("get",path, headers)

def api_del(path, headers) -> requests.Response:
    return _api_call("del",path, headers)

def api_json(path, headers, jsonData) -> requests.Response:
    return _api_call("json",path, headers, jsonData)

def api_multipart(path, headers, data=None, filesData=None):
    return _api_call("multipart", path, headers, data, filesData)

#TODO: REMOVE THIS
def pretty_print_POST(req):
    logging.error('REQUEST THAT CAUSED THE ERROR:\n{}\n{}\r\n{}\r\n\r\n{}'.format(
        '-----------START-----------',
        req.method + ' ' + req.url,
        '\r\n'.join('{}: {}'.format(k, v) for k, v in req.headers.items()),
        req.body,
    ))