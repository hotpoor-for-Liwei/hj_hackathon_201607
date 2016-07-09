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
class UserLogoutAPIHandler(WebRequest):
    def get(self):
        self.post()
    def post(self):
        self.clear_cookie("user")
        self.finish({"hotpoor":"logout"})

class LogoutAPIHandler(WebRequest):
    def get(self):
        self.clear_cookie("user")
        self.redirect("/")

class SMSYunpianSendAPIHandler(WebRequest):
    def get(self):
        self.post()
    @tornado.gen.coroutine
    def post(self):
    	self.finish({"error":"no work"})

class UserSetHeadImgUrlAPIHandler(WebRequest):
    def get(self):
        if not self.current_user:
            return
        self.finish({"":""})
        return

class UserInfoAPIHandler(WebRequest):
    def get(self):
        self.post()
    def post(self):
        if not self.current_user:
            return
        mobilephone = self.get_argument("mobilephone","")
        country = self.get_argument("country","")
        login = "mobile:+%s%s" % (country,mobilephone)
        result = conn.query("SELECT * FROM index_login WHERE login = %s ORDER BY id ASC", login)
        user_id = ""
        if not result:
            self.finish({"error":"no user"})
            return
        else:
            user_id = result[0].get("entity_id","")
            user = nomagic._get_entity_by_id(user_id)
            self.finish({"id":user_id,"name":user.get("name",u"姓名未填写")})
            return

class UserCheckAPIHandler(tornado.web.RequestHandler):
    def get(self):
        self.post()
    def post(self):
        app = self.get_argument("app","")
        mobilephone = self.get_argument("mobilephone","")
        name = self.get_argument("name","")
        country = self.get_argument("country","")
        mobilephone_code = self.get_argument("mobilephone_code","")
        if not app:
            return
        if app in ["bangfer","wlstation","lovebangfer","hotpoor"]:
            login = "mobile:+%s%s" % (country,mobilephone)
            result = conn.query("SELECT * FROM index_login WHERE login = %s ORDER BY id ASC", login)
            user_id = ""
            if not result:
                user = {}
                user["mobilephone_china"] = mobilephone
                user["mobilephone_code"] = "".join(random.choice(string.digits) for x in range(4))
                user["mobilephone_code_close"] = "true"
                user["password"] = ""
                user["name"] = name
                result = nomagic.auth.create_user(user)
                if result:
                    new_id = result[0]
                    conn.execute("INSERT INTO index_login (login, entity_id,app) VALUES(%s, %s, %s)", login, new_id,app)
                    self.set_secure_cookie("user", tornado.escape.json_encode({"id": new_id, "v":1}),expires=time.time()+63072000)
                    self.finish({"info":"reload"})
                    return
                else:
                    return
            else:
                user_id = result[0].get("entity_id","")
                user = nomagic._get_entity_by_id(user_id)
                if user.get("mobilephone_code_close","true") == "true":
                    self.set_secure_cookie("user", tornado.escape.json_encode({"id": user_id, "v":1}),expires=time.time()+63072000)
                    self.finish({"info":"reload"})
                    return
                else:
                    # ==== 助通短信 ====
                    if mobilephone_code:
                        sms_content = u"【HOTPOOR序】您的访问码是：%s，如非本人操作，请勿略本短信。" % user["mobilephone_code"]
                        sms_dstime = ''                          #为空代表立即发送  如果加了时间代表定时发送  精确到秒
                        sms_mobile = mobilephone
                        sms_username = "hotpoor"                 #短信帐号用户名
                        sms_password = "Shelly911223"            #短信帐号密码
                        sms_productid = "676766"                 #内容 676766
                        sms_xh = ''                              #留空

                        sms_url="http://www.ztsms.cn:8800/sendSms.do?username=%s&password=%s&mobile=%s&content=%s&dstime=%s&productid=%s&xh=%s" % (sms_username, sms_password, sms_mobile, urllib.quote(sms_content.encode("utf8")), sms_dstime,sms_productid,sms_xh)
                        client = tornado.httpclient.AsyncHTTPClient()
                        client.fetch(sms_url)
                        self.finish({"info":"waiting code"})
                        return
                    else:
                        if mobilephone_code == user["mobilephone_code"]:
                            self.set_secure_cookie("user", tornado.escape.json_encode({"id": user_id, "v":1}),expires=time.time()+63072000)
                            self.finish({"info":"reload"})
                            return
                        else:
                            self.finish({"info":"code error"})
                            return
        else:
            return

class MainHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self,app):
        self.finish({"info": "welcome"})

class WeixinDownloadHotpoorAPIHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self):
        access_token = self.get_argument("access_token","")
        media_id = self.get_argument("media_id","")
        if not access_token or not media_id:
            self.finish({"info":"not right"})
            return
        print access_token
        print media_id
        url = "http://file.api.weixin.qq.com/cgi-bin/media/get?access_token=%s&media_id=%s" % (access_token, media_id)
        print url
        filename = os.path.join("static/test",media_id)
        print filename
        urllib.urlretrieve(url,filename,Schedule)
        print "finish"
        q = qiniu.auth.Auth(qiniu_hotpoor_access_key,qiniu_hotpoor_secret_key)
        bucket_name = 'hotpoor'
        key = 'hotpoor_weixin_amr_%s' % int(time.time())
        saveas_key = base64.b64encode("hotpoor:%s"%key)
        fops = 'avthumb/m4a|saveas/'+ saveas_key
        policy = {
            'persistentOps':fops
        }
        token = q.upload_token(bucket_name, key, 3600, policy)
        localfile = filename

        ret, info = put_file(token, key, localfile)
        print info
        assert ret['key'] == key
        assert ret['hash'] == etag(localfile)
        os.remove(filename)
        print "--------"
        print "| done |"
        print "--------"

def Schedule(a,b,c):
    '''''
    a:已经下载的数据块
    b:数据块的大小
    c:远程文件的大小
    '''
    per = 100.0 * a * b / c
    if per > 100 :
        per = 100
    print '%.2f%%' % per

class HomeEventOrdersListNewAPIHandler(WebRequest):
    @tornado.gen.coroutine
    def post(self):
        return
        # if not self.current_user:
        #     return
        # first_event_order_id = self.get_argument("first_event_order_id",None)
        # if not first_event_order_id:
        #     return
        # user_id = self.current_user["id"]
        # user = nomagic._get_entity_by_id(user_id)
        # orders_json = []
        # members_json = {}
        # members_ids = set()
        # self.finish({"orders":orders_json,"members":members_json,"first_event_order_id":first_event_order_id})
class HomeEventOrdersListOldAPIHandler(WebRequest):
    @tornado.gen.coroutine
    def post(self):
        return
        # if not self.current_user:
        #     return
        # last_event_order_id = self.get_argument("last_event_order_id",None)
        # if not last_event_order_id:
        #     return
        # user_id = self.current_user["id"]
        # user = nomagic._get_entity_by_id(user_id)
        # orders_json = []
        # members_json = {}
        # members_ids = set()

        # for order in orders:
        #     members_ids = members_ids | set(order[1]["members"])
        #     members_ids = members_ids | set(order[1]["editors"])
        #     orders_json.append(order)
        # members = nomagic._get_entities_by_ids(members_ids)
        # for member in members:
        #     members_json[member[0]] = {"name":member[1].get("name","") or member[1].get("mobilephone_china",u"普通用户"),"tel":member[1].get("mobilephone_china","15201950688")}
        # self.finish({"orders":orders_json,"members":members_json,"last_event_order_id":last_event_order_id})
class HomeEventOrdersListAPIHandler(WebRequest):
    @tornado.gen.coroutine
    def post(self):
        if not self.current_user:
            return
        user_id = self.current_user["id"]
        user = nomagic._get_entity_by_id(user_id)
        event_order_list_ids = user.get("event_orders",[])
        event_orders = nomagic._get_entities_by_ids(event_order_list_ids)
        orders_json = []
        members_json = {}
        members_ids = set()
        order_number_now = 0
        first_event_order_id = None
        last_event_order_id = None
        for order in event_orders:
            if order_number_now == 0:
                first_event_order_id = order[0]
            members_ids = members_ids | set(order[1].get("members",[]))
            members_ids = members_ids | set(order[1].get("editors",[]))
            orders_json.append(order)
            order_number_now = order_number_now + 1
            last_event_order_id = order[0]
            if order_number_now >= 50:
                break
        members = nomagic._get_entities_by_ids(members_ids)
        for member in members:
            members_json[member[0]] = {"name":member[1].get("name","") or member[1].get("mobilephone_china",u"普通用户"),"tel":member[1].get("mobilephone_china","15201950688")}

        self.finish({"orders":orders_json,"members":members_json,"first_event_order_id":first_event_order_id,"last_event_order_id":last_event_order_id})

class HomeEventAddOrderAPIHandler(WebRequest):
    def get(self):
        self.post()
    @tornado.gen.coroutine
    def post(self):
        if not self.current_user:
            return
        order = {}
        self.app = "hotpoor"
        user_id = self.current_user["id"]
        order_max_price = self.get_argument("order_max_price",0)
        order["owner"] = user_id
        order["payment_fee"] = self.get_argument("payment_fee",0)
        order["payment_status"] = self.get_argument("payment_status","")
        order["desc"] = self.get_argument("desc","")
        order["transport"] = self.get_argument("transport","")
        order["app"] = "hotpoor"
        order["subtype"] = "event_order"
        order["subtype_status"] = self.get_argument("subtype_status",u"建立契约中")
        order["remark"] = [[order["owner"],self.get_argument("remark_text",u"创建了本契约哟"),int(time.time())]]
        order["editors"] = [user_id]
        order["members"] = [user_id]
        order["title"] = self.get_argument("title", u"一个新の契约")

        user = nomagic._get_entity_by_id(user_id)
        result = nomagic.order.create_order(order)
        order_id = result[0]
        user_name = user.get("name",user.get("weixin_data",{}).get(self.app,{}).get("nickname",u"匿名"))

        #推送配送线路人员
        http_client = tornado.httpclient.AsyncHTTPClient()
        access_token = weixin_JS_SDK_access_tokens.get(order["app"],"")
        url = "https://api.weixin.qq.com/cgi-bin/message/template/send?access_token="+access_token
        remark = u"\n@%s: %s" % (user_name, self.get_argument("remark_text",u"没有留下些什么"))

        # 推送到除了发起者以外的所有人
        editors = nomagic._get_entities_by_ids(set(order["editors"]))
        for editor in editors:
            if editor[1].get("hotpoor_openids",[]):
                openid = editor[1].get("hotpoor_openids",[])[0]
            else:
                openid = ''
            if access_token and openid:
                first = u"契约の精神 您正有新的一条加入"
                keyword1 = order["title"]
                keyword2 = time.strftime('%Y-%m-%d %H:%M')
                keyword3 = order["subtype_status"]
                json = {
                    "touser":openid,
                    "template_id":weixin_apps_dev_info.get(order["app"],{}).get("template_id_order_event_create",""),
                    "url":"http://www.hotpoor.org/home/event/%s" % order_id,
                    "topcolor":"#dd4b39",
                    "data":{
                        "first":{"value":first,"color":"#000000"},
                        "keyword1":{"value":keyword1,"color":"#dd4b39"},
                        "keyword2":{"value":keyword2,"color":"#000000"},
                        "keyword3":{"value":keyword3,"color":"#dd4b39"},
                        "remark":{"value":remark,"color":"#000000"},
                    },
                }
                body = json_encode(json)
                request = tornado.httpclient.HTTPRequest(
                            url = url,
                            method = "POST",
                            body = body)
                response = yield http_client.fetch(request)
                print response.body

        orders = user.get("event_orders",[])
        orders.insert(0,result[0])
        user["event_orders"] = orders
        nomagic.auth.update_user(user_id,user)

        self.finish({"info":"created"})
        return

class HomeEventUpdateOrderAPIHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self):
        self.finish({})

class HomeEventEditorsListAPIHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self):
        self.finish({})

class HomeEventAddEditorAPIHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self):
        self.finish({})

class HomeEventRemoveEditorAPIHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self):
        self.finish({})

class HomeEventMembersListAPIHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self):
        self.finish({})

class HomeEventAddMemberAPIHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self):
        self.finish({})

class HomeEventRemoveMemberAPIHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self):
        self.finish({})

class HomeEventBaseHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self,entity_id):
        if not self.current_user:
            self.render("template/hotpoor_home_event_start.html")
            return
        user_agent = self.request.headers.get("User-Agent", "")
        self.aim_id = entity_id
        self.user_id = self.current_user["id"]
        self.user = nomagic._get_entity_by_id(self.user_id)
        self.weixin_code = ''
        self.access_token = ''
        self.openid = ''
        app = "hotpoor"
        self.app = app

        self.wx_appid = ''
        self.wx_timestamp = ''
        self.wx_noncestr = ''
        self.wx_signature = ''

        print self.user_id
        print self.aim_id
        print "========="
        if self.aim_id == self.user_id:
            self.aim = self.user
        else:
            self.aim = nomagic._get_entity_by_id(self.aim_id)
        self.aim_type = "error"
        if not self.aim:
            self.redirect('/home/event')
            return
        else:
            self.aim_type = self.aim.get("type","error")
            if not self.aim_type in ["user", "order", "station", "doc", "excel", "ppt", "group"]:
                self.render("template/hotpoor_home_event_error.html")
                return
        weixin_app = self.app
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

            # print "====== bangfer"
            # print weixin_JS_SDK_access_tokens
            sign = WeixinJSSDKSign(weixin_JS_SDK_jsapi_tickets[weixin_app], weixin_JS_SDK_access_token_timers[weixin_app], self.request.full_url())
            self.wx_app = weixin_app
            self.wx_appid = weixin_apps_dev_info[weixin_app].get("AppId","")
            self.wx_ret = sign.sign()
            self.wx_timestamp = self.wx_ret['timestamp']
            self.wx_noncestr = self.wx_ret['nonceStr']
            self.wx_signature = self.wx_ret['signature']

        if "Mobile" in user_agent and "MicroMessenger" in user_agent:
            if app in weixin_apps:
                #获取当前用户open_id
                code = self.get_argument('code','')
                if code:
                    self.weixin_code = code
                    http_client = tornado.httpclient.AsyncHTTPClient()
                    url = 'https://api.weixin.qq.com/sns/oauth2/access_token?appid='+weixin_apps_dev_info[app].get("AppId","")+'&secret='+weixin_apps_dev_info[app].get("AppSecret","")+'&code='+code+'&grant_type=authorization_code'
                    response = yield http_client.fetch(url)
                    data = tornado.escape.json_decode(response.body)
                    if data.get('errcode','') == 40029:
                        if entity_id:
                            self.redirect('/home/event/%s?app=%s'%(entity_id, app))
                        else:
                            self.redirect('/home/event?app=%s'%app)
                        return
                    self.access_token = data.get('access_token')
                    self.openid = data.get('openid')

                    args = {
                        'access_token': self.access_token,
                        'openid'      : self.openid,
                        'lang'        : 'zh_CN'
                    }
                    url = 'https://api.weixin.qq.com/sns/userinfo?' + urllib.urlencode(sorted(args.items()))
                    response = yield http_client.fetch(url)
                    data = json_decode(response.body)
                    if not self.user.get("weixin_data",None):
                        self.user["weixin_data"] = {}
                    self.user["weixin_data"][self.app] = data
                    nomagic.auth.update_user(self.user_id,self.user)
                    print "=========="

                else:
                    # if not users[user_id].get("weixin",{}).get(app,{}).get("weixin_data",{}).get("unionid",""):
                    if entity_id:
                        redirect_uri = 'http://www.hotpoor.org/home/event/%s?app=%s' % (entity_id, app)
                    else:
                        redirect_uri = 'http://www.hotpoor.org/home/event?app=%s' % app
                    args = {
                        'appid'            : weixin_apps_dev_info[app].get("AppId",""),
                        'redirect_uri'     : redirect_uri,
                        'response_type'    : 'code',
                        'scope'            : 'snsapi_userinfo',
                        'state'            : 'hotpoor'
                    }
                    url = 'https://open.weixin.qq.com/connect/oauth2/authorize?' + urllib.urlencode(sorted(args.items())) + '#wechat_redirect'
                    self.redirect(url)
                    return
        self.user_headimgurl = self.user.get("weixin_data",{}).get(self.app,{}).get("headimgurl","https://dn-shimo-image.qbox.me/gyOX61VBhFkZOpx6.jpg")
        self.title = u"序·契约の精神 | Home Event"
        if "Mobile" in user_agent:
            if "Android" in user_agent:
                self.device_type = "Android"
                # self.render("template/hotpoor_home_map_android.html")
                self.render("template/hotpoor_home_event_ios.html")
            else:
                self.device_type = "iOS"
                self.render("template/hotpoor_home_event_ios.html")
        else:
            self.device_type = "Desktop"
            # self.render("template/hotpoor_home_map_desktop.html")
            self.render("template/hotpoor_home_event_ios.html")
        return

class HomeEventHandler(WebRequest):
    @tornado.gen.coroutine
    def get(self):
        if not self.current_user:
            self.render("template/hotpoor_home_event_start.html")
            return
        user_id = self.current_user["id"]
        order_id = self.get_argument("order_id",None)
        if order_id:
            self.redirect("/home/event/%s" % order_id)
        else:
            self.redirect("/home/event/%s" % user_id)
        return

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
    #/event/*产品系列
    #==========================
    (r"/home/event/api/order_list",HomeEventOrdersListAPIHandler),
    (r"/home/event/api/add_order",HomeEventAddOrderAPIHandler),
    (r"/home/event/api/update_order",HomeEventUpdateOrderAPIHandler),

    (r"/home/event/api/editors_list",HomeEventEditorsListAPIHandler),
    (r"/home/event/api/add_editor",HomeEventAddEditorAPIHandler),
    (r"/home/event/api/remove_editor",HomeEventRemoveEditorAPIHandler),

    (r"/home/event/api/members_list",HomeEventMembersListAPIHandler),
    (r"/home/event/api/add_member",HomeEventAddMemberAPIHandler),
    (r"/home/event/api/remove_member",HomeEventRemoveMemberAPIHandler),

    (r"/home/event/(.*)",HomeEventBaseHandler),
    (r"/home/event",HomeEventHandler),

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
