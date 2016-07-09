#!/bin/env python
#coding=utf-8
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/vendor/')

import tornado
import tornado.options
import tornado.ioloop
import tornado.web
import tornado.websocket
import tornado.escape
import tornado.httpclient
import tornado.gen
import tornado.locale
import tornado.auth
import tornado.template
from tornado.escape import json_encode, json_decode

import time
import string
import urllib
import random
import hashlib
import uuid
import xmltodict
import base64

import xlrd

from controller import base
from controller import apps_info

from controller.base import WebRequest
from controller.base import WebSocket
from controller.apps_info import hotpoor_apps

import nomagic
import nomagic.order
import nomagic.auth
import nomagic.setting
from nomagic.setting import conn

import requests
import qiniu
from qiniu import put_file, etag, urlsafe_base64_encode

qiniu_hotpoor_access_key = 'nyAmycfeo4-RF6drKPf62_KU1RUvj8lFsrmOqJ9K'
qiniu_hotpoor_secret_key = 'NBaVPYokRuMvmthKWjabxFGCxQ0yx5h-ZSQwsJrk'

yunpian = {
    "sms_send":"https://sms.yunpian.com:443/v1/sms/send.json",
    "port":"443",
    "version":"v1",
    "apikey":"723fdf1f8360cb854421707fcc739d8e"
}

sms_apps = ["hotpoor"]
weixin_apps = ["hotpoor"]
weixin_apps_dev_info = {
    "hotpoor":{
        "ShopNumber":"1285500601",
        "ShopNumberKey":"hotpoorinchina88xlwlovezhanglu36",
        "Id":"gh_fe913d164ebf",
        "AppId":"wx2ca08b0c9fad1e69",
        "AppSecret":"c04fd723f2f80ca97c92fd8cbb072d7f",
    }
}

weixin_JS_SDK_access_tokens = {}
weixin_JS_SDK_jsapi_tickets = {}
weixin_JS_SDK_access_token_timers = {}


class CheckExcelAPIHandler(WebRequest):
    def get(self):
        self.finish({u"info":u"It's necessary to check excel file."})
    def post(self):
        # upload_path = os.path.join(os.path.dirname(__file__),'files')
        file_metas = self.request.files['file']
        print file_metas
        data = xlrd.open_workbook(file_contents=file_metas[0].get('body'),formatting_info=1)
        print data.sheet_names()
        print u"Sheet数量:%s" % len(data.sheets())
        for table in data.sheets():
            nrows = table.nrows
            ncols = table.ncols
            print u"%s行%s列" % (nrows,ncols)
            for i in range(nrows):
                print table.row_values(i)
                for j in range(ncols):
                    print table.cell_value(i,j)
                    print table.cell(i,j)
                    # print table.cell_xf_index(i,j)
                    print "========"



        data_type = self.get_argument("type")
        print "data_type: %s" % data_type


        self.finish({u"type":u"excel",u"data":{}})

class WechatWebpayHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self):
        if "Mobile" in self.request.headers.get("User-Agent", "") and "MicroMessenger" in self.request.headers.get("User-Agent", ""):
            weixin_app = self.get_argument("weixin_app","")
            self.app = weixin_app
            openid = self.get_argument("openid","")
            order_id = self.get_argument("order","")
            user_agent = self.request.headers.get("User-Agent","")
            weixin_version = user_agent[user_agent.index('MicroMessenger/')+15:]
            weixin_version = int(weixin_version[:weixin_version.index('.')])
            weixin_pay = False
            if weixin_version >=5:
                weixin_pay = True
            if not weixin_pay:
                self.finish(u"This Wechat Version is not ok for Payment!")
                return
            if weixin_app in weixin_apps:
                #获取JSSDK
                if (int(time.time()) - weixin_JS_SDK_access_token_timers.get(weixin_app,0)) > 3600:
                    weixin_JS_SDK_access_token_timers[weixin_app] = int(time.time())
                    http_client = tornado.httpclient.AsyncHTTPClient()
                    url = "https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid="+weixin_apps_dev_info.get(weixin_app, "").get("AppId","")+"&secret="+weixin_apps_dev_info.get(weixin_app, "").get("AppSecret","")
                    response = yield http_client.fetch(url)
                    data = tornado.escape.json_decode(response.body)
                    weixin_JS_SDK_access_tokens[weixin_app] = data.get('access_token')
                    url = "https://api.weixin.qq.com/cgi-bin/ticket/getticket?access_token="+weixin_JS_SDK_access_tokens[weixin_app]+"&type=jsapi"
                    response = yield http_client.fetch(url)
                    data = tornado.escape.json_decode(response.body)
                    weixin_JS_SDK_jsapi_tickets[weixin_app] = data.get('ticket')

                # print "======"
                # print weixin_JS_SDK_access_tokens
                sign = WeixinJSSDKSign(weixin_JS_SDK_jsapi_tickets[weixin_app], weixin_JS_SDK_access_token_timers[weixin_app], self.request.full_url())
                self.wx_app = weixin_app
                self.wx_appid = weixin_apps_dev_info[weixin_app].get("AppId","")
                self.wx_ret = sign.sign()
                self.wx_timestamp = self.wx_ret['timestamp']
                self.wx_noncestr = self.wx_ret['nonceStr']
                self.wx_signature = self.wx_ret['signature']
                if not self.current_user:
                    return
                self.user_id = self.current_user['id']
                #获取open_id
                self.openid = openid

                if self.openid:
                    order = nomagic._get_entity_by_id(order_id)
                    if not order:
                        self.finish(u"Can't find this order!")
                        return
                    self.body = order.get("subtype",u"Hotpoor序·支付平台")
                    self.price = int(order.get("payment_fee","1"))
                    self.payment_status = order.get("payment_status",u"未支付")
                    print self.payment_status
                    remote_ip = self.request.headers.get("X-Forwarded-For", "").split(", ")[0] or self.request.remote_ip
                #     trade_no = conn.execute_lastrowid("INSERT INTO payment_weixin (user_id, doc_id, prepay_info, transaction_info, fee, transaction_id, other_info) VALUES (%s, '', '', '', 0, '', %s)", current_user_id, json_encode({"ref_id": ""}))
                    trade_no = int(time.time())
                    # nonce = uuid.uuid4().hex
                    nonce = self.wx_noncestr
                    # print "uuid:%s" % nonce
                    output = u"""<xml>
    <appid>%s</appid>
    <attach>%s_%s_%s</attach>
    <body>%s</body>
    <mch_id>%s</mch_id>
    <nonce_str>%s</nonce_str>
    <notify_url>http://www.hotpoor.org/wechat/webpay/callback/%s</notify_url>
    <openid>%s</openid>
    <out_trade_no>%s</out_trade_no>
    <spbill_create_ip>%s</spbill_create_ip>
    <total_fee>%s</total_fee>
    <trade_type>JSAPI</trade_type>
    <sign>%s</sign>
</xml>""" % (   weixin_apps_dev_info[weixin_app].get("AppId",""),
                weixin_app,
                self.user_id,
                order_id,
                self.body,
                weixin_apps_dev_info[weixin_app].get("ShopNumber",""),
                nonce,
                # order_id,
                weixin_app,
                self.openid,
                trade_no,
                remote_ip,
                self.price,
             "%s")

                    data = xmltodict.parse(output)["xml"]
                    del data["sign"]
                    temp_str = "&".join(["%s=%s" % (k.encode("utf8"), v.encode('utf8')) for k, v in data.items()])
                    # temp_str += "&key=%s" % weixin_apps_dev_info[weixin_app].get("ShopNumber","")
                    temp_str += "&key=%s" % weixin_apps_dev_info[weixin_app].get("ShopNumberKey","")
                    sign = hashlib.md5(temp_str).hexdigest().upper()
                    xml = output % sign
                    # xml = String(xml.toString().getBytes(), "ISO8859-1")
                    # print xml
                    http_client = tornado.httpclient.AsyncHTTPClient()
                    request = tornado.httpclient.HTTPRequest(
                                url = "https://api.mch.weixin.qq.com/pay/unifiedorder",
                                method = "POST",
                                body = xml)
                    response = yield http_client.fetch(request)
                    # conn.execute("UPDATE payment_weixin SET prepay_info = %s WHERE id = %s", response.body, trade_no)
                    result = xmltodict.parse(response.body)["xml"]
                    # print "^^^^^^^^^"
                    # print result
                    self.prepay_id = result["prepay_id"]
                    # self.timestamp = str(int(time.time()))
                    self.timestamp = str(self.wx_timestamp)
                    # self.nonce = uuid.uuid4().hex
                    self.nonce = result["nonce_str"]

                    data = {
                        "appId": weixin_apps_dev_info[weixin_app].get("AppId",""),
                        "nonceStr": self.nonce,
                        "timeStamp": self.timestamp,
                        "package": "prepay_id=%s" % self.prepay_id,
                        "signType": "MD5",
                    }
                    # print data
                    # print self.wx_timestamp
                    # print self.wx_noncestr
                    temp_str = "&".join(["%s=%s" % (k.encode("utf8"), data[k].encode('utf8')) for k in sorted(data.keys())])
                    temp_str += "&key=%s" % weixin_apps_dev_info[weixin_app].get("ShopNumberKey","")
                    self.pay_sign = hashlib.md5(temp_str).hexdigest().upper()



                self.render("template/wechat_web_pay.html")
                # self.finish({"weixin_app":weixin_app,"webpaytest":"ok"})
            else:
                self.finish({"weixin_app":weixin_app,"webpay":"noapp"})

class WechatWebpayCallbackHandler(WebRequest):
    def post(self,weixin_app):
        weixin_app = weixin_app
        if weixin_app in weixin_apps:
            data = xmltodict.parse(self.request.body)["xml"]
            sign = data["sign"]
            del data["sign"]

            temp_str = "&".join(["%s=%s" % (k.encode("utf8"), data[k].encode('utf8')) for k in sorted(data.keys())])
            temp_str += "&key=%s" % weixin_apps_dev_info[weixin_app].get("ShopNumberKey","")
            if sign != hashlib.md5(temp_str).hexdigest().upper():
                raise tornado.web.HTTPError(403)
                return
            fee = data["total_fee"]
            transaction_id = data["transaction_id"]
            out_trade_no = data["out_trade_no"]
            app,user_id,order_id =  data["attach"].split("_")
            return_code = data["return_code"]
            if return_code == "SUCCESS":
                if app == "bangfer" or app == "hotpoor" or app == "lovebangfer":
                    order = nomagic._get_entity_by_id(order_id)
                    if order["payment_status"] == u"未支付":
                        order_content = u"微信支付成功"
                        order["payment_status"] = u"已支付"
                        order["weixin_pay_call_back"] = data
                        board = [user_id,order_content,int(time.time())]
                        order["remark"].insert(0,board)
                        nomagic.order.update_order(order_id,order)
                        conn.execute("INSERT INTO index_weixin_pay (user_id,order_id,fee,app,createtime,transaction_id,out_trade_no,done,finishtime) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)", user_id,order_id,fee,app,board[2],transaction_id,out_trade_no,1,board[2])

class WechatWebpayTestHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self):
        if "Mobile" in self.request.headers.get("User-Agent", "") and "MicroMessenger" in self.request.headers.get("User-Agent", ""):
            weixin_app = self.get_argument("weixin_app","")
            self.app = weixin_app
            openid = self.get_argument("openid","")
            order_id = self.get_argument("order","")
            user_agent = self.request.headers.get("User-Agent","")
            weixin_version = user_agent[user_agent.index('MicroMessenger/')+15:]
            weixin_version = int(weixin_version[:weixin_version.index('.')])
            weixin_pay = False
            if weixin_version >=5:
                weixin_pay = True
            if not weixin_pay:
                self.finish(u"This Wechat Version is not ok for Payment!")
                return
            if weixin_app in weixin_apps:
                #获取JSSDK
                if (int(time.time()) - weixin_JS_SDK_access_token_timers.get(weixin_app,0)) > 3600:
                    weixin_JS_SDK_access_token_timers[weixin_app] = int(time.time())
                    http_client = tornado.httpclient.AsyncHTTPClient()
                    url = "https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid="+weixin_apps_dev_info.get(weixin_app, "").get("AppId","")+"&secret="+weixin_apps_dev_info.get(weixin_app, "").get("AppSecret","")
                    response = yield http_client.fetch(url)
                    data = tornado.escape.json_decode(response.body)
                    weixin_JS_SDK_access_tokens[weixin_app] = data.get('access_token')
                    url = "https://api.weixin.qq.com/cgi-bin/ticket/getticket?access_token="+weixin_JS_SDK_access_tokens[weixin_app]+"&type=jsapi"
                    response = yield http_client.fetch(url)
                    data = tornado.escape.json_decode(response.body)
                    weixin_JS_SDK_jsapi_tickets[weixin_app] = data.get('ticket')

                # print "======"
                # print weixin_JS_SDK_access_tokens
                sign = WeixinJSSDKSign(weixin_JS_SDK_jsapi_tickets[weixin_app], weixin_JS_SDK_access_token_timers[weixin_app], self.request.full_url())
                self.wx_app = weixin_app
                self.wx_appid = weixin_apps_dev_info[weixin_app].get("AppId","")
                self.wx_ret = sign.sign()
                self.wx_timestamp = self.wx_ret['timestamp']
                self.wx_noncestr = self.wx_ret['nonceStr']
                self.wx_signature = self.wx_ret['signature']
                if not self.current_user:
                    return
                self.user_id = self.current_user['id']
                #获取open_id
                self.openid = openid

                if self.openid:
                    order = nomagic._get_entity_by_id(order_id)
                    if not order:
                        self.finish(u"Can't find this order!")
                        return
                    self.body = order.get("subtype",u"Hotpoor序·支付平台")
                    self.price = int(order.get("payment_fee","1"))
                    self.payment_status = order.get("payment_status",u"未支付")
                    print self.payment_status
                    remote_ip = self.request.headers.get("X-Forwarded-For", "").split(", ")[0] or self.request.remote_ip
                #     trade_no = conn.execute_lastrowid("INSERT INTO payment_weixin (user_id, doc_id, prepay_info, transaction_info, fee, transaction_id, other_info) VALUES (%s, '', '', '', 0, '', %s)", current_user_id, json_encode({"ref_id": ""}))
                    trade_no = int(time.time())
                    # nonce = uuid.uuid4().hex
                    nonce = self.wx_noncestr
                    # print "uuid:%s" % nonce
                    output = u"""<xml>
    <appid>%s</appid>
    <attach>%s_%s_%s</attach>
    <body>%s</body>
    <mch_id>%s</mch_id>
    <nonce_str>%s</nonce_str>
    <notify_url>http://www.hotpoor.org/wechat/webpaytest/callback/%s</notify_url>
    <openid>%s</openid>
    <out_trade_no>%s</out_trade_no>
    <spbill_create_ip>%s</spbill_create_ip>
    <total_fee>%s</total_fee>
    <trade_type>JSAPI</trade_type>
    <sign>%s</sign>
</xml>""" % (   weixin_apps_dev_info[weixin_app].get("AppId",""),
                weixin_app,
                self.user_id,
                order_id,
                self.body,
                weixin_apps_dev_info[weixin_app].get("ShopNumber",""),
                nonce,
                # order_id,
                weixin_app,
                self.openid,
                trade_no,
                remote_ip,
                self.price,
             "%s")

                    data = xmltodict.parse(output)["xml"]
                    del data["sign"]
                    temp_str = "&".join(["%s=%s" % (k.encode("utf8"), v.encode('utf8')) for k, v in data.items()])
                    # temp_str += "&key=%s" % weixin_apps_dev_info[weixin_app].get("ShopNumber","")
                    temp_str += "&key=%s" % weixin_apps_dev_info[weixin_app].get("ShopNumberKey","")
                    sign = hashlib.md5(temp_str).hexdigest().upper()
                    xml = output % sign
                    # xml = String(xml.toString().getBytes(), "ISO8859-1")
                    # print xml
                    http_client = tornado.httpclient.AsyncHTTPClient()
                    request = tornado.httpclient.HTTPRequest(
                                url = "https://api.mch.weixin.qq.com/pay/unifiedorder",
                                method = "POST",
                                body = xml)
                    response = yield http_client.fetch(request)
                    # conn.execute("UPDATE payment_weixin SET prepay_info = %s WHERE id = %s", response.body, trade_no)
                    result = xmltodict.parse(response.body)["xml"]
                    # print "^^^^^^^^^"
                    # print result
                    self.prepay_id = result["prepay_id"]
                    # self.timestamp = str(int(time.time()))
                    self.timestamp = str(self.wx_timestamp)
                    # self.nonce = uuid.uuid4().hex
                    self.nonce = result["nonce_str"]

                    data = {
                        "appId": weixin_apps_dev_info[weixin_app].get("AppId",""),
                        "nonceStr": self.nonce,
                        "timeStamp": self.timestamp,
                        "package": "prepay_id=%s" % self.prepay_id,
                        "signType": "MD5",
                    }
                    # print data
                    # print self.wx_timestamp
                    # print self.wx_noncestr
                    temp_str = "&".join(["%s=%s" % (k.encode("utf8"), data[k].encode('utf8')) for k in sorted(data.keys())])
                    temp_str += "&key=%s" % weixin_apps_dev_info[weixin_app].get("ShopNumberKey","")
                    self.pay_sign = hashlib.md5(temp_str).hexdigest().upper()



                self.render("template/wechat_web_pay_test.html")
                # self.finish({"weixin_app":weixin_app,"webpaytest":"ok"})
            else:
                self.finish({"weixin_app":weixin_app,"webpaytest":"noapp"})

class WechatWebpayTestCallbackHandler(WebRequest):
    def post(self,weixin_app):
        weixin_app = weixin_app
        if weixin_app in weixin_apps:
            data = xmltodict.parse(self.request.body)["xml"]
            sign = data["sign"]
            del data["sign"]

            temp_str = "&".join(["%s=%s" % (k.encode("utf8"), data[k].encode('utf8')) for k in sorted(data.keys())])
            temp_str += "&key=%s" % weixin_apps_dev_info[weixin_app].get("ShopNumberKey","")
            if sign != hashlib.md5(temp_str).hexdigest().upper():
                raise tornado.web.HTTPError(403)
                return
            fee = data["total_fee"]
            transaction_id = data["transaction_id"]
            out_trade_no = data["out_trade_no"]
            app,user_id,order_id =  data["attach"].split("_")
            return_code = data["return_code"]
            if return_code == "SUCCESS":
                if app == "bangfer" or app == "hotpoor" or app == "lovebangfer":
                    order = nomagic._get_entity_by_id(order_id)
                    if order["payment_status"] == u"未支付":
                        order_content = u"微信支付成功"
                        order["payment_status"] = u"已支付"
                        order["weixin_pay_call_back"] = data
                        board = [user_id,order_content,int(time.time())]
                        order["remark"].insert(0,board)
                        nomagic.order.update_order(order_id,order)
                        conn.execute("INSERT INTO index_weixin_pay (user_id,order_id,fee,app,createtime,transaction_id,out_trade_no,done,finishtime) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)", user_id,order_id,fee,app,board[2],transaction_id,out_trade_no,1,board[2])

class WebSocketHandler(tornado.websocket.WebSocketHandler):
    clients = set()
    @staticmethod
    def send_to_all(message):
        for c in WebSocketHandler.clients:
            c.write_message(message)
        print message

    def open(self):
        self.write_message("Welcome to WebSocket")
        WebSocketHandler.send_to_all(str(id(self)) + 'has joined')
        WebSocketHandler.clients.add(self)

    def on_close(self):
        WebSocketHandler.clients.remove(self)
        WebSocketHandler.send_to_all(str(id(self)) + 'has left')


settings = {
    "static_path":os.path.join(os.path.dirname(__file__),"static"),
    "cookie_secret": "hotpoorinchina"
    }

application = tornado.web.Application([
    (r"/api/file/check_excel",CheckExcelAPIHandler),

    (r"/api/user/update_weixin_data/",UpdateWeixinDataUserAPIHandler),

    #==========================
    #微信相关服务器配置、API和支付等
    #==========================
    #支付授权目录
    (r"/wechat/webpay/",WechatWebpayHandler),
    (r"/wechat/webpay/callback/(.*)",WechatWebpayCallbackHandler),
    #测试授权目录
    (r"/wechat/webpaytest/",WechatWebpayTestHandler),
    (r"/wechat/webpaytest/callback/(.*)",WechatWebpayTestCallbackHandler),
    #支付回调URL 微信扫码支付
    (r"/wechat/qrcodepaybackurl/",WechatQrcodepaybackurlHandler),

    (r"/wechat/developer/api/hotpoor",WechatDeveloperAPIHotpoorHandler),

    #==========================
    #/map/(.*)产品系列 独立
    #==========================
    (r"/home/map/(.*)",                     HomeMapBaseHandler),
    (r"/home/map",                          HomeMapHandler),

    #==========================
    #/tools/(.*)产品系列 独立
    #==========================
    (r"/home/tools/webgl_panorama_dualfisheye", HomeToolsWebglPanoramaDualfisheyeHandler),
    (r"/home/tools/webgl_video_panorama_equirectangular", HomeToolsWebglVideoPanoramaEquirectangularHandler),

    #==========================
    #/home/*产品系列 所有其他产品在这个上面得
    #==========================
    (r"/home/(.*)", HomeHandler),

    #==========================
    #/api/*产品系列
    #==========================
    (r"/api/weixin/hotpoor/download",   WeixinDownloadHotpoorAPIHandler),
    (r"/api/user/check",                UserCheckAPIHandler),
    (r"/api/user/info",                 UserInfoAPIHandler),
    # (r"/api/user/add",              UserAddAPIHandler),
    # (r"/api/user/set_password",     UserSetPasswordAPIHandler),
    # (r"/api/user/set_name",         UserSetNameAPIHandler),
    (r"/api/user/set_headimgurl",       UserSetHeadImgUrlAPIHandler),

    (r"/api/sms/yunpian/send", SMSYunpianSendAPIHandler),

    #==========================
    #退出应用
    #==========================
    (r"/api/user/logout",   UserLogoutAPIHandler),
    (r"/logout",            LogoutAPIHandler),

    #==========================
    #其他
    #==========================
    (r"/ws",WebSocketHandler),
    (r"/static/(.*)", tornado.web.StaticFileHandler, dict(path=settings['static_path'])),
    (r"/(.*)", MainHandler),
    ], **settings)

if __name__ == "__main__":
    tornado.options.define("port", default=8036, help="Run server on a specific port", type=int)
    tornado.options.parse_command_line()
    application.listen(tornado.options.options.port)
    tornado.ioloop.IOLoop.instance().start()
    # application.listen(8036)
    # tornado.ioloop.IOLoop.current().start()
